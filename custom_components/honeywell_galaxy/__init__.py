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
from .device import get_entry_area_id, register_devices, sync_device_areas
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

    sync_device_areas(hass, entry)
    _async_schedule_area_syncs(hass, entry)
    entry.async_on_unload(_async_listen_for_device_area_changes(hass, entry))

    hass.async_create_task(auto_add_cards(hass, entry))

    return True


@callback
def _sync_areas_and_cards(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Sync device areas and schedule dashboard cards when an area is assigned."""
    sync_device_areas(hass, entry)
    if get_entry_area_id(hass, entry):
        schedule_add_cards(hass, entry)


@callback
def _async_schedule_area_syncs(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Re-sync areas after setup UI may assign devices to an area."""

    @callback
    def _sync_areas(_now) -> None:
        _sync_areas_and_cards(hass, entry)

    for delay in AREA_SYNC_DELAYS:
        entry.async_on_unload(async_call_later(hass, delay, _sync_areas))


@callback
def _async_listen_for_device_area_changes(
    hass: HomeAssistant, entry: ConfigEntry
) -> callback:
    """Propagate area changes across all integration devices."""

    @callback
    def _handle_device_registry_update(event: Event) -> None:
        data = event.data
        if data.get("action") != "update":
            return

        device_registry = dr.async_get(hass)
        device = device_registry.async_get(data["device_id"])
        if device is None or entry.entry_id not in device.config_entries:
            return

        sync_device_areas(hass, entry)
        if get_entry_area_id(hass, entry):
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
