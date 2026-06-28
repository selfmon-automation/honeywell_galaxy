"""Device definitions for Honeywell Galaxy integration."""
from __future__ import annotations

from typing import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo

from .const import (
    DEVICE_TYPE_GROUPS,
    DEVICE_TYPE_PHYSICAL_RIO,
    DEVICE_TYPE_VIRTUAL_KEYPAD,
    DEVICE_TYPE_VIRTUAL_PRINTER,
    DEVICE_TYPE_VIRTUAL_RIO,
    DOMAIN,
)

MANUFACTURER = "SelfMon"


def hub_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for the Honeywell Galaxy hub."""
    vmodid = entry.data.get("vmodid", "")
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title or f"Honeywell Galaxy ({vmodid})",
        manufacturer=MANUFACTURER,
        model=f"VMOD {vmodid}",
    )


def virtual_keypad_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for the Virtual Keypad."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id, DEVICE_TYPE_VIRTUAL_KEYPAD)},
        name="Virtual Keypad",
        manufacturer=MANUFACTURER,
        model="VMOD Virtual Keypad",
        via_device=(DOMAIN, entry.entry_id),
    )


def virtual_printer_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for the Virtual Printer."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id, DEVICE_TYPE_VIRTUAL_PRINTER)},
        name="Virtual Printer",
        manufacturer=MANUFACTURER,
        model="VMOD Virtual Printer",
        via_device=(DOMAIN, entry.entry_id),
    )


def physical_rio_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for Physical RIO inputs and outputs."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id, DEVICE_TYPE_PHYSICAL_RIO)},
        name="Physical RIO",
        manufacturer=MANUFACTURER,
        model="VMOD Physical RIO",
        via_device=(DOMAIN, entry.entry_id),
    )


def virtual_rio_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for Virtual RIO zones and outputs."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id, DEVICE_TYPE_VIRTUAL_RIO)},
        name="Virtual RIO",
        manufacturer=MANUFACTURER,
        model="VMOD Virtual RIO",
        via_device=(DOMAIN, entry.entry_id),
    )


def groups_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for alarm group status sensors."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id, DEVICE_TYPE_GROUPS)},
        name="Galaxy Groups",
        manufacturer=MANUFACTURER,
        model="VMOD SIA4 Groups",
        via_device=(DOMAIN, entry.entry_id),
    )


CHILD_DEVICE_INFO_FACTORIES: tuple[
    Callable[[ConfigEntry], DeviceInfo], ...
] = (
    virtual_keypad_device_info,
    virtual_printer_device_info,
    physical_rio_device_info,
    virtual_rio_device_info,
    groups_device_info,
)


def _device_info_to_registry_kwargs(info: DeviceInfo) -> dict:
    """Convert DeviceInfo to device registry keyword arguments."""
    return {
        "identifiers": info["identifiers"],
        "manufacturer": info.get("manufacturer"),
        "model": info.get("model"),
        "name": info.get("name"),
        "via_device": info.get("via_device"),
    }


def register_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register hub and child devices before entities are created."""
    device_registry = dr.async_get(hass)
    all_device_infos = [hub_device_info(entry), *[fn(entry) for fn in CHILD_DEVICE_INFO_FACTORIES]]

    for info in all_device_infos:
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            **_device_info_to_registry_kwargs(info),
        )


@callback
def sync_device_areas(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Copy the hub device area to all child devices."""
    device_registry = dr.async_get(hass)
    hub = device_registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    if hub is None or hub.area_id is None:
        return

    for factory in CHILD_DEVICE_INFO_FACTORIES:
        info = factory(entry)
        device = device_registry.async_get_device(identifiers=info["identifiers"])
        if device is not None and device.area_id != hub.area_id:
            device_registry.async_update_device(device.id, area_id=hub.area_id)
