"""Services for Honeywell Galaxy integration."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import DOMAIN, TOPIC_VPRINTER
from .lovelace import auto_add_cards

_LOGGER = logging.getLogger(__name__)

SERVICE_PRINT_TEXT = "print_text"
SERVICE_TEST_MQTT = "test_mqtt"
SERVICE_ADD_DASHBOARD_CARDS = "add_dashboard_cards"

SERVICE_PRINT_TEXT_SCHEMA = vol.Schema(
    {
        vol.Required("text"): cv.string,
    }
)

SERVICE_TEST_MQTT_SCHEMA = vol.Schema(
    {
        vol.Required("topic"): cv.string,
        vol.Required("payload"): cv.string,
    }
)

SERVICE_ADD_DASHBOARD_CARDS_SCHEMA = vol.Schema({})


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Honeywell Galaxy."""

    async def print_text(call: ServiceCall) -> None:
        """Print text to virtual printer."""
        text = call.data.get("text", "")
        if not text:
            _LOGGER.error("No text provided for print_text service")
            return

        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("No Honeywell Galaxy integration configured")
            return

        entry = entries[0]
        coordinator = hass.data[DOMAIN][entry.entry_id]
        vmodid = entry.data.get("vmodid", "")

        topic = f"{TOPIC_VPRINTER.format(vmodid=vmodid)}/print"
        coordinator.publish(topic, text)
        _LOGGER.info("Printed text to virtual printer: %s", text)

    async def test_mqtt(call: ServiceCall) -> None:
        """Test MQTT publishing."""
        topic = call.data.get("topic", "")
        payload = call.data.get("payload", "")

        if not topic or not payload:
            _LOGGER.error("Topic and payload are required for test_mqtt service")
            return

        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("No Honeywell Galaxy integration configured")
            return

        entry = entries[0]
        coordinator = hass.data[DOMAIN][entry.entry_id]

        _LOGGER.info(
            "Testing MQTT publish: topic=%s, payload=%s, connected=%s",
            topic,
            payload,
            coordinator.connected,
        )
        coordinator.publish(topic, payload)
        _LOGGER.info("MQTT test publish completed")

    async def add_dashboard_cards(call: ServiceCall) -> None:
        """Rebuild Galaxy Lovelace cards on the assigned area dashboard view."""
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("No Honeywell Galaxy integration configured")
            return

        for entry in entries:
            await auto_add_cards(hass, entry, delay_seconds=0, full_dashboard=True)

    hass.services.async_register(
        DOMAIN, SERVICE_PRINT_TEXT, print_text, schema=SERVICE_PRINT_TEXT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_TEST_MQTT, test_mqtt, schema=SERVICE_TEST_MQTT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_DASHBOARD_CARDS,
        add_dashboard_cards,
        schema=SERVICE_ADD_DASHBOARD_CARDS_SCHEMA,
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload services for Honeywell Galaxy."""
    hass.services.async_remove(DOMAIN, SERVICE_PRINT_TEXT)
    hass.services.async_remove(DOMAIN, SERVICE_TEST_MQTT)
    hass.services.async_remove(DOMAIN, SERVICE_ADD_DASHBOARD_CARDS)
