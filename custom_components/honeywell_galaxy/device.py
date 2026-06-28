"""Device definitions for Honeywell Galaxy integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
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
        via_device={(DOMAIN, entry.entry_id)},
    )


def virtual_printer_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for the Virtual Printer."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id, DEVICE_TYPE_VIRTUAL_PRINTER)},
        name="Virtual Printer",
        manufacturer=MANUFACTURER,
        model="VMOD Virtual Printer",
        via_device={(DOMAIN, entry.entry_id)},
    )


def physical_rio_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for Physical RIO inputs and outputs."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id, DEVICE_TYPE_PHYSICAL_RIO)},
        name="Physical RIO",
        manufacturer=MANUFACTURER,
        model="VMOD Physical RIO",
        via_device={(DOMAIN, entry.entry_id)},
    )


def virtual_rio_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for Virtual RIO zones and outputs."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id, DEVICE_TYPE_VIRTUAL_RIO)},
        name="Virtual RIO",
        manufacturer=MANUFACTURER,
        model="VMOD Virtual RIO",
        via_device={(DOMAIN, entry.entry_id)},
    )


def groups_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for alarm group status sensors."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id, DEVICE_TYPE_GROUPS)},
        name="Galaxy Groups",
        manufacturer=MANUFACTURER,
        model="VMOD SIA4 Groups",
        via_device={(DOMAIN, entry.entry_id)},
    )
