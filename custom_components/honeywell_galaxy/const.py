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

# MQTT discovery timing
MQTT_CONNECT_MAX_SECONDS = 5
DISCOVERY_MAX_SECONDS = 4
DISCOVERY_IDLE_SECONDS = 1.0
DISCOVERY_POLL_INTERVAL = 0.25

# Device types
DEVICE_TYPE_VIRTUAL_KEYPAD = "virtual_keypad"
DEVICE_TYPE_VIRTUAL_PRINTER = "virtual_printer"
DEVICE_TYPE_VIRTUAL_RIO = "virtual_rio"
DEVICE_TYPE_PHYSICAL_RIO = "physical_rio"
DEVICE_TYPE_GROUPS = "groups"
