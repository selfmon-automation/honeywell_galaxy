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


def virtual_keypad_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for the Virtual Keypad."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id, DEVICE_TYPE_VIRTUAL_KEYPAD)},
        name="Virtual Keypad",
        manufacturer=MANUFACTURER,
        model="VMOD Virtual Keypad",
    )


def virtual_printer_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for the Virtual Printer."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id, DEVICE_TYPE_VIRTUAL_PRINTER)},
        name="Virtual Printer",
        manufacturer=MANUFACTURER,
        model="VMOD Virtual Printer",
    )


def physical_rio_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for Physical RIO inputs and outputs."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id, DEVICE_TYPE_PHYSICAL_RIO)},
        name="Physical RIO",
        manufacturer=MANUFACTURER,
        model="VMOD Physical RIO",
    )


def virtual_rio_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for Virtual RIO zones and outputs."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id, DEVICE_TYPE_VIRTUAL_RIO)},
        name="Virtual RIO",
        manufacturer=MANUFACTURER,
        model="VMOD Virtual RIO",
    )


def groups_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for alarm group status sensors."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id, DEVICE_TYPE_GROUPS)},
        name="Galaxy Groups",
        manufacturer=MANUFACTURER,
        model="VMOD SIA4 Groups",
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
    """Register child devices before entities are created."""
    device_registry = dr.async_get(hass)

    for factory in CHILD_DEVICE_INFO_FACTORIES:
        info = factory(entry)
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            **_device_info_to_registry_kwargs(info),
        )


@callback
def get_device_type(device: dr.DeviceEntry) -> str | None:
    """Return the Honeywell Galaxy device type identifier, if known."""
    for domain, _entry_id, device_type in device.identifiers:
        if domain == DOMAIN:
            return device_type
    return None


@callback
def iter_devices_with_areas(
    hass: HomeAssistant, entry: ConfigEntry
) -> list[dr.DeviceEntry]:
    """Return integration devices that have an area assigned."""
    device_registry = dr.async_get(hass)
    return [
        device
        for device in dr.async_entries_for_config_entry(
            device_registry, entry.entry_id
        )
        if device.area_id and get_device_type(device) is not None
    ]
