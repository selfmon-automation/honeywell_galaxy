"""Support for Honeywell Galaxy Virtual RIO Zones."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, TOPIC_VRIO_INPUTS, TOPIC_VRIO_INPUTS_READ
from .coordinator import GalaxyCoordinator
from .device import virtual_rio_device_info
from .mqtt_discovery import discover_mqtt_numeric_ids

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Honeywell Galaxy Virtual RIO Zones."""
    coordinator: GalaxyCoordinator = hass.data[DOMAIN][entry.entry_id]
    vmodid = entry.data.get("vmodid", "")

    entities = []

    zones = entry.options.get("virtual_rio_zones", [])
    
    if not zones:
        _LOGGER.info("No Virtual RIO zones configured. Discovering zones from MQTT topics...")
        discovered_zones = await discover_mqtt_numeric_ids(
            coordinator,
            f"{TOPIC_VRIO_INPUTS_READ.format(vmodid=vmodid)}/+",
            label="Virtual RIO zone",
        )
        _LOGGER.info(
            "Discovered %s Virtual RIO zones: %s",
            len(discovered_zones),
            sorted(discovered_zones),
        )
        for zone_num in discovered_zones:
            entities.append(
                VirtualRIOZone(
                    coordinator, entry, vmodid, zone_num, None
                )
            )
    else:
        for zone_config in zones:
            entities.append(
                VirtualRIOZone(
                    coordinator, entry, vmodid, zone_config.get("zone_number"), zone_config.get("name")
                )
            )

    if not entities:
        _LOGGER.warning("No Virtual RIO Zones configured. Add zones via integration options.")

    async_add_entities(entities)


class VirtualRIOZone(CoordinatorEntity, SwitchEntity):
    """Representation of a Virtual RIO Zone."""

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
        self._vrio_write_topic = TOPIC_VRIO_INPUTS.format(vmodid=vmodid)
        self._vrio_read_topic = TOPIC_VRIO_INPUTS_READ.format(vmodid=vmodid)
        self._is_on = False

        self._attr_unique_id = f"{entry.entry_id}_vrio_zone_{zone_number}"
        self._attr_name = name or f"Zone {zone_number}"
        self._attr_device_info = virtual_rio_device_info(entry)

    @property
    def is_on(self) -> bool:
        """Return true if the zone is open."""
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the zone on (OPEN)."""
        await self._set_zone_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the zone off (CLOSED)."""
        await self._set_zone_state(False)

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

    async def _set_zone_state(self, state: bool) -> None:
        """Set zone state via MQTT."""
        topic = f"{self._vrio_write_topic}/{self._zone_number}"
        payload = "OPEN" if state else "CLOSED"
        self.coordinator.publish(topic, payload)
        self._is_on = state
        self.async_write_ha_state()
        _LOGGER.debug(f"Set zone {self._zone_number} to {payload}")
