"""Support for Honeywell Galaxy sensors."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, TOPIC_SIA4_EVENT, TOPIC_SIA4_GROUPS, TOPIC_VKP, TOPIC_VPRINTER
from .coordinator import GalaxyCoordinator
from .device import (
    alarm_reporting_device_info,
    groups_device_info,
    virtual_keypad_device_info,
    virtual_printer_device_info,
)
from .mqtt_discovery import discover_mqtt_numeric_ids

_LOGGER = logging.getLogger(__name__)

LOG_LINE_MAX = 10
ALARM_REPORTING_DISABLED = frozenset({"disabled", "event=disabled"})


def format_alarm_reporting_message(payload: str) -> str | None:
    """Return a formatted alarm report line, or None when reporting is disabled."""
    text = payload.strip()
    if not text or text.casefold() in ALARM_REPORTING_DISABLED:
        return None
    return text.replace("##", "  ")


class _LogLineBuffer:
    """Rolling buffer of log lines for printer-style MQTT text sensors."""

    def __init__(self, max_lines: int = LOG_LINE_MAX) -> None:
        self._log_lines: list[str] = []
        self._max_lines = max_lines
        self._state = ""

    def append(self, message: str) -> None:
        """Append a line and refresh the truncated state value."""
        self._log_lines.append(message)
        if len(self._log_lines) > self._max_lines:
            self._log_lines = self._log_lines[-self._max_lines :]

        full_log = "\n".join(self._log_lines)
        if len(full_log) > 255:
            latest_line = self._log_lines[-1]
            self._state = (
                latest_line[:252] + "..." if len(latest_line) > 255 else latest_line
            )
        else:
            self._state = full_log

        if len(self._state) > 255:
            self._state = self._state[:252] + "..."

    @property
    def state(self) -> str:
        """Return the sensor state, truncated for HA limits."""
        if len(self._state) > 255:
            return self._state[:252] + "..."
        return self._state

    @property
    def extra_attributes(self) -> dict[str, Any]:
        """Return log buffer attributes for Lovelace cards."""
        return {
            "log_lines": self._log_lines.copy(),
            "line_count": len(self._log_lines),
            "max_lines": self._max_lines,
        }

KEYPAD_SENSORS = [
    SensorEntityDescription(
        key="display_line1",
        name="Display Line 1",
        icon="mdi:display",
    ),
    SensorEntityDescription(
        key="display_line2",
        name="Display Line 2",
        icon="mdi:display",
    ),
]

PRINTER_SENSOR = SensorEntityDescription(
    key="printer_log",
    name="Printer Log",
    icon="mdi:printer",
)

ALARM_REPORTING_SENSOR = SensorEntityDescription(
    key="alarm_reporting_log",
    name="Alarm Reporting Log",
    icon="mdi:bell-alert",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Honeywell Galaxy sensors."""
    coordinator: GalaxyCoordinator = hass.data[DOMAIN][entry.entry_id]
    vmodid = entry.data.get("vmodid", "")

    entities = []

    for description in KEYPAD_SENSORS:
        entities.append(KeypadDisplaySensor(coordinator, entry, vmodid, description))

    entities.append(PrinterLogSensor(coordinator, entry, vmodid))
    entities.append(AlarmReportingLogSensor(coordinator, entry, vmodid))

    _LOGGER.info("Discovering groups from MQTT topics...")
    discovered_groups = await discover_mqtt_numeric_ids(
        coordinator,
        f"{TOPIC_SIA4_GROUPS.format(vmodid=vmodid)}/+",
        label="group",
    )
    _LOGGER.info("Discovered %s groups: %s", len(discovered_groups), sorted(discovered_groups))
    for group_num in discovered_groups:
        entities.append(GroupSensor(coordinator, entry, vmodid, group_num))

    async_add_entities(entities)


class KeypadDisplaySensor(CoordinatorEntity, SensorEntity):
    """Representation of a Virtual Keypad Display Line sensor."""

    def __init__(
        self,
        coordinator: GalaxyCoordinator,
        entry: ConfigEntry,
        vmodid: str,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._vmodid = vmodid
        self._description = description
        self._vkp_topic = TOPIC_VKP.format(vmodid=vmodid)
        self._state = ""

        self._attr_unique_id = f"{entry.entry_id}_keypad_{description.key}"
        self._attr_name = description.name
        self._attr_device_info = virtual_keypad_device_info(entry)
        self.entity_description = description

    async def _async_update_state(self, payload: str) -> None:
        """Update state in the event loop."""
        self._state = payload
        self.async_write_ha_state()
        _LOGGER.debug(f"Updated state for {self._description.key} to: {self._state}")

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT topics when added to hass."""
        await super().async_added_to_hass()

        topic = f"{self._vkp_topic}/display/{self._description.key.replace('display_', '')}"
        _LOGGER.info(f"Subscribing to display topic: {topic}")

        def handle_message(topic: str, payload: str) -> None:
            """Handle message updates from MQTT thread."""
            _LOGGER.debug(f"Received display update for {self._description.key}: {payload}")
            # Schedule the state update to run in the Home Assistant event loop
            self.hass.loop.call_soon_threadsafe(
                lambda p=payload: self.hass.async_create_task(self._async_update_state(p))
            )

        self.coordinator.subscribe(topic, handle_message)
        _LOGGER.debug(f"Subscription registered for {topic}")

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        return self._state


class PrinterLogSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Virtual Printer Log sensor - maintains last 10 log lines."""

    def __init__(
        self, coordinator: GalaxyCoordinator, entry: ConfigEntry, vmodid: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._vmodid = vmodid
        self._vprinter_topic = TOPIC_VPRINTER.format(vmodid=vmodid)
        self._buffer = _LogLineBuffer()

        self._attr_unique_id = f"{entry.entry_id}_printer_log"
        self._attr_name = PRINTER_SENSOR.name
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = virtual_printer_device_info(entry)
        self.entity_description = PRINTER_SENSOR

    async def _async_update_state(self, payload: str) -> None:
        """Update state in the event loop - add new line to log buffer."""
        message = payload.strip()
        if not message:
            return
        self._buffer.append(message)
        self.async_write_ha_state()
        _LOGGER.debug(
            "Printer log updated, %s lines",
            self._buffer.extra_attributes["line_count"],
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT topics when added to hass."""
        await super().async_added_to_hass()

        topic = f"{self._vprinter_topic}/log"
        _LOGGER.info(f"Subscribing to printer log topic: {topic}")

        def handle_message(topic: str, payload: str) -> None:
            """Handle message updates from MQTT thread."""
            _LOGGER.debug(f"Received printer log message: {payload}")
            self.hass.loop.call_soon_threadsafe(
                lambda p=payload: self.hass.async_create_task(self._async_update_state(p))
            )

        self.coordinator.subscribe(topic, handle_message)
        _LOGGER.debug(f"Subscription registered for {topic}")

    @property
    def native_value(self) -> str:
        """Return the state of the sensor - most recent line or truncated log."""
        return self._buffer.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return self._buffer.extra_attributes


class AlarmReportingLogSensor(CoordinatorEntity, SensorEntity):
    """Representation of an Alarm Reporting log sensor."""

    def __init__(
        self, coordinator: GalaxyCoordinator, entry: ConfigEntry, vmodid: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._vmodid = vmodid
        self._event_topic = TOPIC_SIA4_EVENT.format(vmodid=vmodid)
        self._buffer = _LogLineBuffer()

        self._attr_unique_id = f"{entry.entry_id}_alarm_reporting_log"
        self._attr_name = ALARM_REPORTING_SENSOR.name
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = alarm_reporting_device_info(entry)
        self.entity_description = ALARM_REPORTING_SENSOR

    async def _async_update_state(self, payload: str) -> None:
        """Update state in the event loop - add new alarm report line."""
        message = format_alarm_reporting_message(payload)
        if message is None:
            return
        self._buffer.append(message)
        self.async_write_ha_state()
        _LOGGER.debug(
            "Alarm reporting log updated, %s lines",
            self._buffer.extra_attributes["line_count"],
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT topics when added to hass."""
        await super().async_added_to_hass()

        _LOGGER.info("Subscribing to alarm reporting topic: %s", self._event_topic)

        def handle_message(topic: str, payload: str) -> None:
            """Handle message updates from MQTT thread."""
            _LOGGER.debug("Received alarm reporting message: %s", payload)
            self.hass.loop.call_soon_threadsafe(
                lambda p=payload: self.hass.async_create_task(self._async_update_state(p))
            )

        self.coordinator.subscribe(self._event_topic, handle_message)

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        return self._buffer.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return self._buffer.extra_attributes


class GroupSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Group sensor."""

    def __init__(
        self,
        coordinator: GalaxyCoordinator,
        entry: ConfigEntry,
        vmodid: str,
        group_number: int,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._vmodid = vmodid
        self._group_number = group_number
        self._groups_topic = TOPIC_SIA4_GROUPS.format(vmodid=vmodid)
        self._state = ""

        self._attr_unique_id = f"{entry.entry_id}_group_{group_number}"
        self._attr_name = f"Group {group_number}"
        self._attr_device_info = groups_device_info(entry)

    async def _async_update_state(self, payload: str) -> None:
        """Update state in the event loop."""
        self._state = payload.strip()
        self.async_write_ha_state()
        _LOGGER.debug(f"Updated state for Group {self._group_number} to: {self._state}")

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT topics when added to hass."""
        await super().async_added_to_hass()

        topic = f"{self._groups_topic}/{self._group_number}"
        _LOGGER.info(f"Subscribing to group topic: {topic}")

        def handle_message(topic: str, payload: str) -> None:
            """Handle message updates from MQTT thread."""
            _LOGGER.debug(f"Received group update for Group {self._group_number}: {payload}")
            self.hass.loop.call_soon_threadsafe(
                lambda p=payload: self.hass.async_create_task(self._async_update_state(p))
            )

        self.coordinator.subscribe(topic, handle_message)
        _LOGGER.debug(f"Subscription registered for {topic}")

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        return self._state