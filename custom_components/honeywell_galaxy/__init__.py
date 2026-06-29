"""The Honeywell Galaxy integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import EVENT_DEVICE_REGISTRY_UPDATED
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN
from .coordinator import GalaxyCoordinator
from .device import register_devices
from .lovelace import auto_add_cards, schedule_add_cards
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
]

AREA_SYNC_DELAYS = (5, 30, 60)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Honeywell Galaxy from a config entry."""
    coordinator = GalaxyCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    register_devices(hass, entry)

    if len(hass.data[DOMAIN]) == 1:
        await async_setup_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_schedule_card_retries(hass, entry)
    entry.async_on_unload(_async_listen_for_device_area_changes(hass, entry))

    hass.async_create_task(auto_add_cards(hass, entry))

    return True


@callback
def _async_schedule_card_retries(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Retry dashboard card creation after setup UI may assign device areas."""

    @callback
    def _retry_cards(_now) -> None:
        hass.async_create_task(auto_add_cards(hass, entry, delay_seconds=0))

    for delay in AREA_SYNC_DELAYS:
        entry.async_on_unload(async_call_later(hass, delay, _retry_cards))


@callback
def _async_listen_for_device_area_changes(
    hass: HomeAssistant, entry: ConfigEntry
) -> callback:
    """Add dashboard cards when an integration device is assigned to an area."""

    @callback
    def _handle_device_registry_update(event: Event) -> None:
        data = event.data
        if data.get("action") != "update":
            return

        device_registry = dr.async_get(hass)
        device = device_registry.async_get(data["device_id"])
        if device is None or entry.entry_id not in device.config_entries:
            return

        if device.area_id:
            schedule_add_cards(hass, entry)

    return hass.bus.async_listen(EVENT_DEVICE_REGISTRY_UPDATED, _handle_device_registry_update)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

        if not hass.data[DOMAIN]:
            await async_unload_services(hass)

    return unload_ok
