"""Constants for the Honeywell Galaxy integration."""
from __future__ import annotations

DOMAIN = "honeywell_galaxy"

# MQTT Topic prefixes
TOPIC_VKP = "selfmon/vmod.{vmodid}/vkp"
TOPIC_VPRINTER = "selfmon/vmod.{vmodid}/vprinter"
TOPIC_VRIO_INPUTS = "selfmon/vmod.{vmodid}/vrio/inputs/write"
TOPIC_VRIO_INPUTS_READ = "selfmon/vmod.{vmodid}/vrio/inputs/read"
TOPIC_VRIO_OUTPUTS = "selfmon/vmod.{vmodid}/vrio/outputs"
TOPIC_PRIO_INPUTS = "selfmon/vmod.{vmodid}/prio/inputs/read"
TOPIC_PRIO_OUTPUTS = "selfmon/vmod.{vmodid}/prio/outputs"
TOPIC_SIA4_GROUPS = "selfmon/vmod.{vmodid}/sia4/groups"

# Device types
DEVICE_TYPE_VIRTUAL_KEYPAD = "virtual_keypad"
DEVICE_TYPE_VIRTUAL_PRINTER = "virtual_printer"
DEVICE_TYPE_VIRTUAL_RIO_ZONE = "virtual_rio_zone"
DEVICE_TYPE_VIRTUAL_RIO_OUTPUT = "virtual_rio_output"
DEVICE_TYPE_PHYSICAL_RIO_ZONE = "physical_rio_zone"
DEVICE_TYPE_PHYSICAL_RIO_OUTPUT = "physical_rio_output"
