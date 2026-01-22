"""Support for Honeywell Galaxy sensors."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Set

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, TOPIC_VKP, TOPIC_VPRINTER, TOPIC_SIA4_GROUPS
from .coordinator import GalaxyCoordinator

_LOGGER = logging.getLogger(__name__)

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


async def _discover_groups(coordinator: GalaxyCoordinator, vmodid: str) -> Set[int]:
    """Discover groups by subscribing to MQTT wildcard topic."""
    discovered_groups: Set[int] = set()
    discovery_topic = f"{TOPIC_SIA4_GROUPS.format(vmodid=vmodid)}/+"
    
    def discovery_handler(topic: str, payload: str) -> None:
        """Handle discovery messages."""
        try:
            group_num_str = topic.split("/")[-1]
            group_num = int(group_num_str)
            discovered_groups.add(group_num)
            _LOGGER.warning(f"Discovered group: {group_num} (value: {payload})")
        except (ValueError, IndexError) as e:
            _LOGGER.debug(f"Could not parse group number from topic {topic}: {e}")
    
    if not coordinator.connected:
        _LOGGER.warning("MQTT not connected, waiting for connection...")
        for _ in range(10):
            await asyncio.sleep(1)
            if coordinator.connected:
                break
        if not coordinator.connected:
            _LOGGER.error("MQTT not connected after 10 seconds, cannot discover groups")
            return discovered_groups
    
    _LOGGER.info(f"Subscribing to discovery topic: {discovery_topic}")
    coordinator.subscribe(discovery_topic, discovery_handler)
    
    _LOGGER.warning(f"Waiting 10 seconds for MQTT messages on {discovery_topic}...")
    await asyncio.sleep(10)
    
    _LOGGER.warning(f"Discovery complete. Found {len(discovered_groups)} groups: {sorted(discovered_groups)}")
    coordinator.unsubscribe(discovery_topic, discovery_handler)
    
    return discovered_groups


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

    _LOGGER.warning("Discovering groups from MQTT topics...")
    discovered_groups = await _discover_groups(coordinator, vmodid)
    _LOGGER.warning(f"Discovered {len(discovered_groups)} groups: {sorted(discovered_groups)}")
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
        self._attr_name = f"Honeywell Galaxy {description.name}"
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
        self._log_lines: list[str] = []  # Store last 10 lines in chronological order
        self._max_lines = 10
        self._state = ""  # Initialize state to empty string

        self._attr_unique_id = f"{entry.entry_id}_printer_log"
        self._attr_name = f"Honeywell Galaxy {PRINTER_SENSOR.name}"
        self.entity_description = PRINTER_SENSOR

    async def _async_update_state(self, payload: str) -> None:
        """Update state in the event loop - add new line to log buffer."""
        if payload:
            self._log_lines.append(payload.strip())
            if len(self._log_lines) > self._max_lines:
                self._log_lines = self._log_lines[-self._max_lines:]
            full_log = "\n".join(self._log_lines)
            if len(full_log) > 255:
                if self._log_lines:
                    latest_line = self._log_lines[-1]
                    if len(latest_line) > 255:
                        self._state = latest_line[:252] + "..."
                    else:
                        self._state = latest_line
                else:
                    self._state = ""
            else:
                self._state = full_log
            if len(self._state) > 255:
                self._state = self._state[:252] + "..."
            self.async_write_ha_state()
            _LOGGER.debug(f"Printer log updated, {len(self._log_lines)} lines, state length: {len(self._state)}")

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT topics when added to hass."""
        await super().async_added_to_hass()

        topic = f"{self._vprinter_topic}/log"
        _LOGGER.info(f"Subscribing to printer log topic: {topic}")

        def handle_message(topic: str, payload: str) -> None:
            """Handle message updates from MQTT thread."""
            _LOGGER.debug(f"Received printer log message: {payload}")
            # Schedule the state update to run in the Home Assistant event loop
            self.hass.loop.call_soon_threadsafe(
                lambda p=payload: self.hass.async_create_task(self._async_update_state(p))
            )

        self.coordinator.subscribe(topic, handle_message)
        _LOGGER.debug(f"Subscription registered for {topic}")

    @property
    def native_value(self) -> str:
        """Return the state of the sensor - most recent line or truncated log."""
        if len(self._state) > 255:
            return self._state[:252] + "..."
        return self._state
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "log_lines": self._log_lines.copy(),  # List of all log lines
            "line_count": len(self._log_lines),
            "max_lines": self._max_lines,
        }


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