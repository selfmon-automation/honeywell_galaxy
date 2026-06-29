"""Support for Honeywell Galaxy binary sensors."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    TOPIC_PRIO_INPUTS,
    TOPIC_PRIO_OUTPUTS,
    TOPIC_VRIO_OUTPUTS,
)
from .coordinator import GalaxyCoordinator
from .device import physical_rio_device_info, virtual_rio_device_info
from .mqtt_discovery import discover_mqtt_numeric_ids

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Honeywell Galaxy binary sensors."""
    coordinator: GalaxyCoordinator = hass.data[DOMAIN][entry.entry_id]
    vmodid = entry.data.get("vmodid", "")

    entities = []

    physical_zones = entry.options.get("physical_rio_zones", [])
    physical_outputs = entry.options.get("physical_rio_outputs", [])
    virtual_outputs = entry.options.get("virtual_rio_outputs", [])

    discovery_tasks: dict[str, asyncio.Task[set[int]]] = {}
    if not physical_zones:
        _LOGGER.info(
            "No Physical RIO zones configured. Discovering zones from MQTT topics..."
        )
        discovery_tasks["prio_zones"] = asyncio.create_task(
            discover_mqtt_numeric_ids(
                coordinator,
                f"{TOPIC_PRIO_INPUTS.format(vmodid=vmodid)}/+",
                label="Physical RIO zone",
            )
        )
    if not physical_outputs:
        _LOGGER.info(
            "No Physical RIO outputs configured. Discovering outputs from MQTT topics..."
        )
        discovery_tasks["prio_outputs"] = asyncio.create_task(
            discover_mqtt_numeric_ids(
                coordinator,
                f"{TOPIC_PRIO_OUTPUTS.format(vmodid=vmodid)}/+",
                label="Physical RIO output",
            )
        )
    if not virtual_outputs:
        _LOGGER.info(
            "No Virtual RIO outputs configured. Discovering outputs from MQTT topics..."
        )
        discovery_tasks["vrio_outputs"] = asyncio.create_task(
            discover_mqtt_numeric_ids(
                coordinator,
                f"{TOPIC_VRIO_OUTPUTS.format(vmodid=vmodid)}/+",
                label="Virtual RIO output",
            )
        )

    discovered: dict[str, set[int]] = {}
    if discovery_tasks:
        names = list(discovery_tasks)
        results = await asyncio.gather(*discovery_tasks.values())
        discovered = dict(zip(names, results, strict=True))

    if not physical_zones:
        discovered_zones = discovered.get("prio_zones", set())
        _LOGGER.info(
            "Discovered %s Physical RIO zones: %s",
            len(discovered_zones),
            sorted(discovered_zones),
        )
        for zone_num in discovered_zones:
            entities.append(
                PhysicalRIOZone(
                    coordinator,
                    entry,
                    vmodid,
                    zone_num,
                    None,
                    BinarySensorDeviceClass.DOOR,
                )
            )
    else:
        for zone_config in physical_zones:
            zone_type = zone_config.get("zone_type", "contact")
            device_class = BinarySensorDeviceClass.DOOR
            if zone_type in ["movement", "motion", "pir"]:
                device_class = BinarySensorDeviceClass.MOTION
            elif zone_type in ["panic", "smoke", "alarm"]:
                device_class = BinarySensorDeviceClass.SMOKE

            entities.append(
                PhysicalRIOZone(
                    coordinator,
                    entry,
                    vmodid,
                    zone_config.get("zone_number"),
                    zone_config.get("name"),
                    device_class,
                )
            )

    if not physical_outputs:
        discovered_outputs = discovered.get("prio_outputs", set())
        _LOGGER.info(
            "Discovered %s Physical RIO outputs: %s",
            len(discovered_outputs),
            sorted(discovered_outputs),
        )
        for output_num in discovered_outputs:
            entities.append(
                PhysicalRIOOutput(
                    coordinator,
                    entry,
                    vmodid,
                    output_num,
                    None,
                )
            )
    else:
        for output_config in physical_outputs:
            entities.append(
                PhysicalRIOOutput(
                    coordinator,
                    entry,
                    vmodid,
                    output_config.get("output_number"),
                    output_config.get("name"),
                )
            )

    if not virtual_outputs:
        discovered_vrio_outputs = discovered.get("vrio_outputs", set())
        _LOGGER.info(
            "Discovered %s Virtual RIO outputs: %s",
            len(discovered_vrio_outputs),
            sorted(discovered_vrio_outputs),
        )
        for output_num in discovered_vrio_outputs:
            entities.append(
                VirtualRIOOutput(
                    coordinator,
                    entry,
                    vmodid,
                    output_num,
                    None,
                )
            )
    else:
        for output_config in virtual_outputs:
            entities.append(
                VirtualRIOOutput(
                    coordinator,
                    entry,
                    vmodid,
                    output_config.get("output_number"),
                    output_config.get("name"),
                )
            )

    if not entities:
        _LOGGER.warning("No binary sensors configured. Add zones/outputs via integration options.")

    async_add_entities(entities)


class PhysicalRIOZone(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Physical RIO Zone."""

    def __init__(
        self,
        coordinator: GalaxyCoordinator,
        entry: ConfigEntry,
        vmodid: str,
        zone_number: int,
        name: str | None = None,
        device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.DOOR,
    ) -> None:
        """Initialize the Physical RIO Zone."""
        super().__init__(coordinator)
        self._entry = entry
        self._vmodid = vmodid
        self._zone_number = zone_number
        self._prio_topic = TOPIC_PRIO_INPUTS.format(vmodid=vmodid)
        self._is_on = False

        self._attr_unique_id = f"{entry.entry_id}_prio_zone_{zone_number}"
        self._attr_name = name or f"Zone {zone_number}"
        self._attr_device_class = device_class
        self._attr_device_info = physical_rio_device_info(entry)

    async def _async_update_state(self, is_on: bool) -> None:
        """Update state in the event loop."""
        self._is_on = is_on
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT topics when added to hass."""
        await super().async_added_to_hass()

        topic = f"{self._prio_topic}/{self._zone_number}"

        def handle_message(topic: str, payload: str) -> None:
            """Handle message updates from MQTT thread."""
            payload_upper = payload.strip().upper()
            is_on = payload_upper == "OPEN"
            # Schedule the state update to run in the Home Assistant event loop
            self.hass.loop.call_soon_threadsafe(
                lambda state=is_on: self.hass.async_create_task(self._async_update_state(state))
            )

        self.coordinator.subscribe(topic, handle_message)

    @property
    def is_on(self) -> bool:
        """Return true if the zone is open."""
        return self._is_on


class PhysicalRIOOutput(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Physical RIO Output."""

    def __init__(
        self,
        coordinator: GalaxyCoordinator,
        entry: ConfigEntry,
        vmodid: str,
        output_number: int,
        name: str | None = None,
    ) -> None:
        """Initialize the Physical RIO Output."""
        super().__init__(coordinator)
        self._entry = entry
        self._vmodid = vmodid
        self._output_number = output_number
        self._prio_topic = TOPIC_PRIO_OUTPUTS.format(vmodid=vmodid)
        self._is_on = False

        self._attr_unique_id = f"{entry.entry_id}_prio_output_{output_number}"
        self._attr_name = name or f"Output {output_number}"
        self._attr_device_class = None
        self._attr_device_info = physical_rio_device_info(entry)

    async def _async_update_state(self, is_on: bool) -> None:
        """Update state in the event loop."""
        self._is_on = is_on
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT topics when added to hass."""
        await super().async_added_to_hass()

        topic = f"{self._prio_topic}/{self._output_number}"

        def handle_message(topic: str, payload: str) -> None:
            """Handle message updates from MQTT thread."""
            payload_upper = payload.strip().upper()
            is_on = payload_upper == "ON"
            # Schedule the state update to run in the Home Assistant event loop
            self.hass.loop.call_soon_threadsafe(
                lambda state=is_on: self.hass.async_create_task(self._async_update_state(state))
            )

        self.coordinator.subscribe(topic, handle_message)

    @property
    def is_on(self) -> bool:
        """Return true if the output is on."""
        return self._is_on


class VirtualRIOOutput(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Virtual RIO Output."""

    def __init__(
        self,
        coordinator: GalaxyCoordinator,
        entry: ConfigEntry,
        vmodid: str,
        output_number: int,
        name: str | None = None,
    ) -> None:
        """Initialize the Virtual RIO Output."""
        super().__init__(coordinator)
        self._entry = entry
        self._vmodid = vmodid
        self._output_number = output_number
        self._vrio_topic = TOPIC_VRIO_OUTPUTS.format(vmodid=vmodid)
        self._is_on = False

        self._attr_unique_id = f"{entry.entry_id}_vrio_output_{output_number}"
        self._attr_name = name or f"Output {output_number}"
        self._attr_device_class = None
        self._attr_device_info = virtual_rio_device_info(entry)

    async def _async_update_state(self, is_on: bool) -> None:
        """Update state in the event loop."""
        self._is_on = is_on
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT topics when added to hass."""
        await super().async_added_to_hass()

        topic = f"{self._vrio_topic}/{self._output_number}"

        def handle_message(topic: str, payload: str) -> None:
            """Handle message updates from MQTT thread."""
            payload_upper = payload.strip().upper()
            is_on = payload_upper == "ON"
            # Schedule the state update to run in the Home Assistant event loop
            self.hass.loop.call_soon_threadsafe(
                lambda state=is_on: self.hass.async_create_task(self._async_update_state(state))
            )

        self.coordinator.subscribe(topic, handle_message)

    @property
    def is_on(self) -> bool:
        """Return true if the output is on."""
        return self._is_on
