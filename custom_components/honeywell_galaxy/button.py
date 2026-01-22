"""Support for Honeywell Galaxy Virtual Keypad buttons."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, TOPIC_VKP
from .coordinator import GalaxyCoordinator

_LOGGER = logging.getLogger(__name__)

KEYPAD_BUTTONS = [
    {"key": "1", "name": "Key 1", "icon": "mdi:numeric-1"},
    {"key": "2", "name": "Key 2", "icon": "mdi:numeric-2"},
    {"key": "3", "name": "Key 3", "icon": "mdi:numeric-3"},
    {"key": "A", "name": "Key A>", "icon": "mdi:arrow-right-bold"},
    {"key": "4", "name": "Key 4", "icon": "mdi:numeric-4"},
    {"key": "5", "name": "Key 5", "icon": "mdi:numeric-5"},
    {"key": "6", "name": "Key 6", "icon": "mdi:numeric-6"},
    {"key": "B", "name": "Key B<", "icon": "mdi:arrow-left-bold"},
    {"key": "7", "name": "Key 7", "icon": "mdi:numeric-7"},
    {"key": "8", "name": "Key 8", "icon": "mdi:numeric-8"},
    {"key": "9", "name": "Key 9", "icon": "mdi:numeric-9"},
    {"key": "E", "name": "Enter", "icon": "mdi:check"},
    {"key": "*", "name": "Asterisk", "icon": "mdi:asterisk"},
    {"key": "0", "name": "Key 0", "icon": "mdi:numeric-0"},
    {"key": "#", "name": "Hash", "icon": "mdi:pound"},
    {"key": "X", "name": "Escape", "icon": "mdi:close"},
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Honeywell Galaxy Virtual Keypad buttons."""
    coordinator: GalaxyCoordinator = hass.data[DOMAIN][entry.entry_id]
    vmodid = entry.data.get("vmodid", "")

    entities = []
    for button_config in KEYPAD_BUTTONS:
        entities.append(
            KeypadButton(coordinator, entry, vmodid, button_config["key"], button_config["name"], button_config["icon"])
        )

    async_add_entities(entities)


class KeypadButton(CoordinatorEntity, ButtonEntity):
    """Representation of a Virtual Keypad button."""

    def __init__(
        self,
        coordinator: GalaxyCoordinator,
        entry: ConfigEntry,
        vmodid: str,
        key: str,
        name: str,
        icon: str,
    ) -> None:
        """Initialize the keypad button."""
        super().__init__(coordinator)
        self._entry = entry
        self._vmodid = vmodid
        self._key = key
        self._vkp_topic = TOPIC_VKP.format(vmodid=vmodid)

        key_name = key.lower().replace("*", "asterisk").replace("#", "hash")
        if key_name == "a":
            key_name = "key_a"
        elif key_name == "b":
            key_name = "key_b"
        elif key_name == "e":
            key_name = "enter"
        elif key_name == "x":
            key_name = "escape"
        
        self._attr_unique_id = f"{entry.entry_id}_keypad_button_{key_name}"
        self._attr_name = f"Honeywell Galaxy {name}"
        self._attr_icon = icon

    async def async_press(self) -> None:
        """Handle the button press."""
        topic = f"{self._vkp_topic}/key"
        _LOGGER.info(f"Button pressed: {self._key}, publishing to {topic}")
        self.coordinator.publish(topic, self._key)
        _LOGGER.debug(f"Pressed keypad button: {self._key} -> {topic}")
