"""Support for Honeywell Galaxy binary sensors."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Set

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    TOPIC_PRIO_INPUTS,
    TOPIC_PRIO_OUTPUTS,
    TOPIC_VRIO_OUTPUTS,
)
from .coordinator import GalaxyCoordinator

_LOGGER = logging.getLogger(__name__)


async def _discover_prio_zones(coordinator: GalaxyCoordinator, vmodid: str) -> Set[int]:
    """Discover Physical RIO zones by subscribing to MQTT wildcard topic."""
    discovered_zones: Set[int] = set()
    discovery_topic = f"{TOPIC_PRIO_INPUTS.format(vmodid=vmodid)}/+"
    
    def discovery_handler(topic: str, payload: str) -> None:
        """Handle discovery messages."""
        try:
            zone_num_str = topic.split("/")[-1]
            zone_num = int(zone_num_str)
            discovered_zones.add(zone_num)
            _LOGGER.warning(f"Discovered Physical RIO zone: {zone_num} (value: {payload})")
        except (ValueError, IndexError) as e:
            _LOGGER.debug(f"Could not parse zone number from topic {topic}: {e}")
    
    if not coordinator.connected:
        _LOGGER.warning("MQTT not connected, waiting for connection...")
        for _ in range(10):
            await asyncio.sleep(1)
            if coordinator.connected:
                break
        if not coordinator.connected:
            _LOGGER.error("MQTT not connected after 10 seconds, cannot discover zones")
            return discovered_zones
    
    _LOGGER.info(f"Subscribing to discovery topic: {discovery_topic}")
    coordinator.subscribe(discovery_topic, discovery_handler)
    
    _LOGGER.warning(f"Waiting 10 seconds for MQTT messages on {discovery_topic}...")
    await asyncio.sleep(10)
    
    _LOGGER.warning(f"Discovery complete. Found {len(discovered_zones)} zones: {sorted(discovered_zones)}")
    coordinator.unsubscribe(discovery_topic, discovery_handler)
    
    return discovered_zones


async def _discover_prio_outputs(coordinator: GalaxyCoordinator, vmodid: str) -> Set[int]:
    """Discover Physical RIO outputs by subscribing to MQTT wildcard topic."""
    discovered_outputs: Set[int] = set()
    discovery_topic = f"{TOPIC_PRIO_OUTPUTS.format(vmodid=vmodid)}/+"
    
    def discovery_handler(topic: str, payload: str) -> None:
        """Handle discovery messages."""
        try:
            output_num_str = topic.split("/")[-1]
            output_num = int(output_num_str)
            discovered_outputs.add(output_num)
            _LOGGER.warning(f"Discovered Physical RIO output: {output_num} (value: {payload})")
        except (ValueError, IndexError) as e:
            _LOGGER.debug(f"Could not parse output number from topic {topic}: {e}")
    
    if not coordinator.connected:
        _LOGGER.warning("MQTT not connected, waiting for connection...")
        for _ in range(10):
            await asyncio.sleep(1)
            if coordinator.connected:
                break
        if not coordinator.connected:
            _LOGGER.error("MQTT not connected after 10 seconds, cannot discover outputs")
            return discovered_outputs
    
    _LOGGER.info(f"Subscribing to discovery topic: {discovery_topic}")
    coordinator.subscribe(discovery_topic, discovery_handler)
    
    _LOGGER.warning(f"Waiting 10 seconds for MQTT messages on {discovery_topic}...")
    await asyncio.sleep(10)
    
    _LOGGER.warning(f"Discovery complete. Found {len(discovered_outputs)} outputs: {sorted(discovered_outputs)}")
    coordinator.unsubscribe(discovery_topic, discovery_handler)
    
    return discovered_outputs


async def _discover_vrio_outputs(coordinator: GalaxyCoordinator, vmodid: str) -> Set[int]:
    """Discover Virtual RIO outputs by subscribing to MQTT wildcard topic."""
    discovered_outputs: Set[int] = set()
    discovery_topic = f"{TOPIC_VRIO_OUTPUTS.format(vmodid=vmodid)}/+"
    
    def discovery_handler(topic: str, payload: str) -> None:
        """Handle discovery messages."""
        try:
            output_num_str = topic.split("/")[-1]
            output_num = int(output_num_str)
            discovered_outputs.add(output_num)
            _LOGGER.warning(f"Discovered Virtual RIO output: {output_num} (value: {payload})")
        except (ValueError, IndexError) as e:
            _LOGGER.debug(f"Could not parse output number from topic {topic}: {e}")
    
    if not coordinator.connected:
        _LOGGER.warning("MQTT not connected, waiting for connection...")
        for _ in range(10):
            await asyncio.sleep(1)
            if coordinator.connected:
                break
        if not coordinator.connected:
            _LOGGER.error("MQTT not connected after 10 seconds, cannot discover outputs")
            return discovered_outputs
    
    _LOGGER.info(f"Subscribing to discovery topic: {discovery_topic}")
    coordinator.subscribe(discovery_topic, discovery_handler)
    
    _LOGGER.warning(f"Waiting 10 seconds for MQTT messages on {discovery_topic}...")
    await asyncio.sleep(10)
    
    _LOGGER.warning(f"Discovery complete. Found {len(discovered_outputs)} Virtual RIO outputs: {sorted(discovered_outputs)}")
    coordinator.unsubscribe(discovery_topic, discovery_handler)
    
    return discovered_outputs


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
    
    if not physical_zones:
        _LOGGER.warning("No Physical RIO zones configured. Discovering zones from MQTT topics...")
        discovered_zones = await _discover_prio_zones(coordinator, vmodid)
        _LOGGER.warning(f"Discovered {len(discovered_zones)} Physical RIO zones: {sorted(discovered_zones)}")
        for zone_num in discovered_zones:
            entities.append(
                PhysicalRIOZone(
                    coordinator,
                    entry,
                    vmodid,
                    zone_num,
                    f"Physical RIO Zone {zone_num}",
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

    physical_outputs = entry.options.get("physical_rio_outputs", [])
    
    if not physical_outputs:
        _LOGGER.warning("No Physical RIO outputs configured. Discovering outputs from MQTT topics...")
        discovered_outputs = await _discover_prio_outputs(coordinator, vmodid)
        _LOGGER.warning(f"Discovered {len(discovered_outputs)} Physical RIO outputs: {sorted(discovered_outputs)}")
        for output_num in discovered_outputs:
            entities.append(
                PhysicalRIOOutput(
                    coordinator,
                    entry,
                    vmodid,
                    output_num,
                    f"Physical RIO Output {output_num}",
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

    virtual_outputs = entry.options.get("virtual_rio_outputs", [])
    
    if not virtual_outputs:
        _LOGGER.warning("No Virtual RIO outputs configured. Discovering outputs from MQTT topics...")
        discovered_vrio_outputs = await _discover_vrio_outputs(coordinator, vmodid)
        _LOGGER.warning(f"Discovered {len(discovered_vrio_outputs)} Virtual RIO outputs: {sorted(discovered_vrio_outputs)}")
        for output_num in discovered_vrio_outputs:
            entities.append(
                VirtualRIOOutput(
                    coordinator,
                    entry,
                    vmodid,
                    output_num,
                    f"Virtual RIO Output {output_num}",
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
        self._attr_name = name or f"Physical RIO Zone {zone_number}"
        self._attr_device_class = device_class

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
        self._attr_name = name or f"Physical RIO Output {output_number}"
        self._attr_device_class = None

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


class VirtualRIOZone(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Virtual RIO Zone (read-only)."""

    def __init__(
        self,
        coordinator: GalaxyCoordinator,
        entry: ConfigEntry,
        vmodid: str,
        zone_number: int,
        name: str | None = None,
    ) -> None:
        """Initialize the Virtual RIO Zone."""
        super().__init__(coordinator)
        self._entry = entry
        self._vmodid = vmodid
        self._zone_number = zone_number
        self._vrio_read_topic = TOPIC_VRIO_INPUTS_READ.format(vmodid=vmodid)
        self._is_on = False

        self._attr_unique_id = f"{entry.entry_id}_vrio_zone_{zone_number}"
        self._attr_name = name or f"Virtual RIO Zone {zone_number}"
        self._attr_device_class = BinarySensorDeviceClass.DOOR

    @property
    def is_on(self) -> bool:
        """Return true if the zone is open."""
        return self._is_on

    async def _async_update_state(self, is_on: bool) -> None:
        """Update state in the event loop."""
        self._is_on = is_on
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT topics when added to hass."""
        await super().async_added_to_hass()

        read_topic = f"{self._vrio_read_topic}/{self._zone_number}"

        def handle_message(topic: str, payload: str) -> None:
            """Handle message updates from MQTT thread."""
            payload_upper = payload.strip().upper()
            is_on = payload_upper == "OPEN"
            self.hass.loop.call_soon_threadsafe(
                lambda state=is_on: self.hass.async_create_task(self._async_update_state(state))
            )

        self.coordinator.subscribe(read_topic, handle_message)


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
        self._attr_name = name or f"Virtual RIO Output {output_number}"
        self._attr_device_class = None

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


class VirtualRIOZone(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Virtual RIO Zone (read-only)."""

    def __init__(
        self,
        coordinator: GalaxyCoordinator,
        entry: ConfigEntry,
        vmodid: str,
        zone_number: int,
        name: str | None = None,
    ) -> None:
        """Initialize the Virtual RIO Zone."""
        super().__init__(coordinator)
        self._entry = entry
        self._vmodid = vmodid
        self._zone_number = zone_number
        self._vrio_read_topic = TOPIC_VRIO_INPUTS_READ.format(vmodid=vmodid)
        self._is_on = False

        self._attr_unique_id = f"{entry.entry_id}_vrio_zone_{zone_number}"
        self._attr_name = name or f"Virtual RIO Zone {zone_number}"
        self._attr_device_class = BinarySensorDeviceClass.DOOR

    @property
    def is_on(self) -> bool:
        """Return true if the zone is open."""
        return self._is_on

    async def _async_update_state(self, is_on: bool) -> None:
        """Update state in the event loop."""
        self._is_on = is_on
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT topics when added to hass."""
        await super().async_added_to_hass()

        read_topic = f"{self._vrio_read_topic}/{self._zone_number}"

        def handle_message(topic: str, payload: str) -> None:
            """Handle message updates from MQTT thread."""
            payload_upper = payload.strip().upper()
            is_on = payload_upper == "OPEN"
            self.hass.loop.call_soon_threadsafe(
                lambda state=is_on: self.hass.async_create_task(self._async_update_state(state))
            )

        self.coordinator.subscribe(read_topic, handle_message)
