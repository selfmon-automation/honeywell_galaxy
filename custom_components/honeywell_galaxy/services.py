"""Services for Honeywell Galaxy integration."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
import voluptuous as vol
import yaml

from .const import DOMAIN, TOPIC_VKP, TOPIC_VPRINTER

_LOGGER = logging.getLogger(__name__)

SERVICE_PRINT_TEXT = "print_text"
SERVICE_TEST_MQTT = "test_mqtt"

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
        _LOGGER.info(f"Printed text to virtual printer: {text}")

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
        
        _LOGGER.info(f"Testing MQTT publish: topic={topic}, payload={payload}, connected={coordinator.connected}")
        coordinator.publish(topic, payload)
        _LOGGER.info("MQTT test publish completed")

    hass.services.async_register(
        DOMAIN, SERVICE_PRINT_TEXT, print_text, schema=SERVICE_PRINT_TEXT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_TEST_MQTT, test_mqtt, schema=SERVICE_TEST_MQTT_SCHEMA
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload services for Honeywell Galaxy."""
    hass.services.async_remove(DOMAIN, SERVICE_PRINT_TEXT)
    hass.services.async_remove(DOMAIN, SERVICE_TEST_MQTT)


async def auto_add_cards(
    hass: HomeAssistant,
    entry: ConfigEntry,
    delay_seconds: int = 5,
) -> None:
    """Automatically add keypad, printer log, and physical RIO cards to dashboard."""
    _LOGGER.warning("=" * 60)
    _LOGGER.warning("auto_add_cards FUNCTION CALLED - Starting card addition")
    _LOGGER.warning("=" * 60)
    
    import asyncio
    await asyncio.sleep(delay_seconds)
    
    try:
        entity_registry = er.async_get(hass)
        vmodid = entry.data.get("vmodid", "")
        entry_id = entry.entry_id
        
        _LOGGER.warning(f"Looking for entities with entry_id: {entry_id}")
        
        entities = {}
        prio_zones = []
        prio_outputs = []
        vrio_zones = []
        vrio_outputs = []
        groups = []
        
        all_entities = list(er.async_entries_for_config_entry(entity_registry, entry_id))
        _LOGGER.warning(f"Found {len(all_entities)} total entities for this config entry")
        
        _LOGGER.warning(f"Looking for Physical RIO entities with unique_id patterns:")
        _LOGGER.warning(f"  - Zones: {entry_id}_prio_zone_*")
        _LOGGER.warning(f"  - Outputs: {entry_id}_prio_output_*")
        
        for entity_entry in all_entities:
            unique_id = entity_entry.unique_id
            entity_id = entity_entry.entity_id
            
            _LOGGER.debug(f"Checking entity: unique_id={unique_id}, entity_id={entity_id}")
            
            if unique_id.endswith("_keypad_display_line1"):
                entities["display_line1"] = entity_id
                _LOGGER.warning(f"Found display_line1: {entity_id}")
            elif unique_id.endswith("_keypad_display_line2"):
                entities["display_line2"] = entity_id
                _LOGGER.warning(f"Found display_line2: {entity_id}")
            elif unique_id.endswith("_printer_log"):
                entities["printer_log"] = entity_id
                _LOGGER.warning(f"Found printer_log: {entity_id}")
            elif unique_id.startswith(f"{entry_id}_prio_zone_"):
                zone_num = unique_id.replace(f"{entry_id}_prio_zone_", "")
                prio_zones.append({
                    "entity_id": entity_id,
                    "name": entity_entry.name or f"Zone {zone_num}",
                    "zone_number": zone_num
                })
                _LOGGER.warning(f"Found Physical RIO Zone: {entity_id} (Zone {zone_num})")
            elif unique_id.startswith(f"{entry_id}_prio_output_"):
                output_num = unique_id.replace(f"{entry_id}_prio_output_", "")
                prio_outputs.append({
                    "entity_id": entity_id,
                    "name": entity_entry.name or f"Output {output_num}",
                    "output_number": output_num
                })
                _LOGGER.warning(f"Found Physical RIO Output: {entity_id} (Output {output_num})")
            elif unique_id.startswith(f"{entry_id}_vrio_output_"):
                output_num = unique_id.replace(f"{entry_id}_vrio_output_", "")
                vrio_outputs.append({
                    "entity_id": entity_id,
                    "name": entity_entry.name or f"Output {output_num}",
                    "output_number": output_num
                })
                _LOGGER.warning(f"Found Virtual RIO Output: {entity_id} (Output {output_num})")
            elif unique_id.startswith(f"{entry_id}_vrio_zone_"):
                zone_num = unique_id.replace(f"{entry_id}_vrio_zone_", "")
                vrio_zones.append({
                    "entity_id": entity_id,
                    "name": entity_entry.name or f"Zone {zone_num}",
                    "zone_number": zone_num
                })
                _LOGGER.warning(f"Found Virtual RIO Zone: {entity_id} (Zone {zone_num})")
            elif unique_id.startswith(f"{entry_id}_group_"):
                group_num = unique_id.replace(f"{entry_id}_group_", "")
                groups.append({
                    "entity_id": entity_id,
                    "name": entity_entry.name or f"Group {group_num}",
                    "group_number": group_num
                })
                _LOGGER.warning(f"Found Group: {entity_id} (Group {group_num})")
        
        if not prio_zones and not prio_outputs and not vrio_zones and not vrio_outputs and not groups:
            _LOGGER.warning("=" * 60)
            _LOGGER.warning("No Physical RIO entities found in entity registry.")
            _LOGGER.warning("To create Physical RIO cards, you need to:")
            _LOGGER.warning("1. Go to Settings > Devices & Services > Honeywell Galaxy")
            _LOGGER.warning("2. Click 'Configure'")
            _LOGGER.warning("3. Add Physical RIO Zones (inputs) and/or Physical RIO Outputs")
            _LOGGER.warning("4. Save and restart Home Assistant")
            _LOGGER.warning("=" * 60)
            _LOGGER.warning("The entities will subscribe to MQTT topics:")
            _LOGGER.warning(f"  - Zones: selfmon/vmod.{vmodid}/prio/inputs/read/{{zone_number}}")
            _LOGGER.warning(f"  - Outputs: selfmon/vmod.{vmodid}/prio/outputs/{{output_number}}")
            _LOGGER.warning("=" * 60)
        
        _LOGGER.warning(f"Summary: {len(prio_zones)} Physical RIO Zones, {len(prio_outputs)} Physical RIO Outputs, {len(vrio_zones)} Virtual RIO Zones, {len(vrio_outputs)} Virtual RIO Outputs, {len(groups)} Groups")
        
        if not entities.get("display_line1") or not entities.get("display_line2"):
            _LOGGER.warning("Keypad display entities not found, retrying in 10 seconds...")
            await asyncio.sleep(10)
            
            for entity_entry in er.async_entries_for_config_entry(entity_registry, entry_id):
                unique_id = entity_entry.unique_id
                entity_id = entity_entry.entity_id
                
                if unique_id.endswith("_keypad_display_line1"):
                    entities["display_line1"] = entity_id
                elif unique_id.endswith("_keypad_display_line2"):
                    entities["display_line2"] = entity_id
        
        if not entities.get("display_line1") or not entities.get("display_line2"):
            _LOGGER.error("Keypad display entities still not found after retry")
            return
        
        mqtt_topic = f"{TOPIC_VKP.format(vmodid=vmodid)}/key"
        
        try:
            template_path = Path(__file__).parent / "keypad_card_template.yaml"
            import asyncio
            loop = asyncio.get_event_loop()
            template_content = await loop.run_in_executor(
                None, 
                lambda: template_path.read_text(encoding="utf-8")
            )
            
            replacements = {
                'XXXXXX_DISPLAY_LINE_1': entities['display_line1'],
                'XXXXXX_DISPLAY_LINE_2': entities['display_line2'],
                'XXXXXX_MQTT_TOPIC': mqtt_topic,
            }
            
            for placeholder, value in replacements.items():
                template_content = template_content.replace(placeholder, value)
            
            keypad_card = yaml.safe_load(template_content)
        except Exception as e:
            _LOGGER.error(f"Failed to load keypad card template: {e}", exc_info=True)
            return
        
        if "lovelace" not in hass.data:
            _LOGGER.error("Lovelace not available")
            return
        
        lovelace = hass.data["lovelace"]
        if not hasattr(lovelace, "dashboards"):
            _LOGGER.error("Lovelace dashboards not available")
            return
        
        dashboards = lovelace.dashboards
        _LOGGER.warning(f"Available dashboards: {list(dashboards.keys())}")
        
        dashboard_id = None
        if None in dashboards:
            actual_dashboard_id = None
            _LOGGER.warning("Using default dashboard (None)")
        elif "lovelace" in dashboards:
            actual_dashboard_id = "lovelace"
            _LOGGER.warning("Using default dashboard 'lovelace'")
        elif "dashboard-lovelace" in dashboards:
            actual_dashboard_id = "dashboard-lovelace"
            _LOGGER.warning("Using default dashboard 'dashboard-lovelace'")
        else:
            actual_dashboard_id = list(dashboards.keys())[0]
            _LOGGER.warning(f"No default dashboard found, using first available: '{actual_dashboard_id}'")
        
        _LOGGER.warning(f"Using dashboard '{actual_dashboard_id}'")
        _LOGGER.warning(f"Found dashboard '{actual_dashboard_id}', loading configuration...")
        default_dashboard = dashboards[actual_dashboard_id]
        _LOGGER.warning(f"Dashboard type: {type(default_dashboard)}, has async_load: {hasattr(default_dashboard, 'async_load')}")
        
        try:
            config = await default_dashboard.async_load(force=False)
            _LOGGER.warning(f"Loaded dashboard config, found {len(config.get('views', []))} view(s)")
        except Exception as load_error:
            _LOGGER.error(f"Failed to load dashboard config: {load_error}", exc_info=True)
            return
        
        if not config:
            _LOGGER.error("Dashboard config is None")
            return
        views = config.get("views", [])
        
        if not views:
            _LOGGER.error("No views found in dashboard")
            return
        
        target_view = views[0]
        
        view_cards = target_view.get("cards", [])
        
        keypad_exists = any(
            card.get("title") == "Galaxy Keypad" or
            (isinstance(card, dict) and card.get("type") == "custom:stack-in-card" and
             any(subcard.get("name") == "VKPDisplay" for subcard in card.get("cards", [])))
            for card in view_cards
        )
        
        if keypad_exists:
            view_cards = [card for card in view_cards if not (
                card.get("title") == "Galaxy Keypad" or
                (isinstance(card, dict) and card.get("type") == "custom:stack-in-card" and
                 any(subcard.get("name") == "VKPDisplay" for subcard in card.get("cards", [])))
            )]
        
        view_cards.append(keypad_card)
        
        if entities.get("printer_log"):
            printer_log_card = {
                "type": "markdown",
                "title": "Honeywell Galaxy Log",
                "content": f"```\n{{{{ (state_attr('{entities['printer_log']}', 'log_lines') or []) | join('\\n') }}}}\n```",
                "card_mod": {
                    "style": "ha-card { background: #f9f9f9; font-family: monospace; font-size: 12px; max-height: 500px; overflow-y: auto; } .markdown { white-space: pre-wrap; }"
                }
            }
            
            printer_log_exists = any(
                card.get("title") == "Honeywell Galaxy Log"
                for card in view_cards
            )
            
            if not printer_log_exists:
                view_cards.append(printer_log_card)
        
        if prio_zones or prio_outputs or vrio_zones or vrio_outputs or groups:
            _LOGGER.warning(f"Creating RIO cards: {len(prio_zones)} Physical zones, {len(prio_outputs)} Physical outputs, {len(vrio_zones)} Virtual zones, {len(vrio_outputs)} Virtual outputs, {len(groups)} Groups")
            prio_cards = []
            
            if prio_zones:
                zone_entities = [
                    zone["entity_id"]
                    for zone in sorted(prio_zones, key=lambda x: int(x["zone_number"]))
                ]
                _LOGGER.warning(f"Creating Physical RIO Inputs card with {len(zone_entities)} entities")
                zones_card = {
                    "type": "entities",
                    "title": "Physical RIO Inputs",
                    "entities": zone_entities
                }
                prio_cards.append(zones_card)
            
            if prio_outputs:
                output_entities = [
                    output["entity_id"]
                    for output in sorted(prio_outputs, key=lambda x: int(x["output_number"]))
                ]
                _LOGGER.warning(f"Creating Physical RIO Outputs card with {len(output_entities)} entities")
                outputs_card = {
                    "type": "entities",
                    "title": "Physical RIO Outputs",
                    "entities": output_entities
                }
                prio_cards.append(outputs_card)
            
            if vrio_zones:
                vrio_zones_card = {
                    "type": "entities",
                    "title": "Virtual RIO Zones",
                    "show_header_toggle": False,
                    "entities": [
                        zone["entity_id"]
                        for zone in sorted(vrio_zones, key=lambda x: int(x["zone_number"]))
                    ]
                }
                prio_cards.append(vrio_zones_card)
            
            if vrio_outputs:
                vrio_output_entities = [
                    output["entity_id"]
                    for output in sorted(vrio_outputs, key=lambda x: int(x["output_number"]))
                ]
                _LOGGER.warning(f"Creating Virtual RIO Outputs card with {len(vrio_output_entities)} entities")
                vrio_outputs_card = {
                    "type": "entities",
                    "title": "Virtual RIO Outputs",
                    "entities": vrio_output_entities
                }
                prio_cards.append(vrio_outputs_card)
            
            if groups:
                group_entities = [
                    group["entity_id"]
                    for group in sorted(groups, key=lambda x: int(x["group_number"]))
                ]
                _LOGGER.warning(f"Creating Groups card with {len(group_entities)} entities")
                groups_card = {
                    "type": "entities",
                    "title": "Groups",
                    "entities": group_entities
                }
                prio_cards.append(groups_card)
            
            for prio_card in prio_cards:
                card_title = prio_card.get("title", "")
                card_exists = any(
                    card.get("title") == card_title
                    for card in view_cards
                )
                
                if not card_exists:
                    _LOGGER.warning(f"Adding card: {card_title}")
                    view_cards.append(prio_card)
                else:
                    _LOGGER.warning(f"Card already exists: {card_title}, skipping")
        else:
            _LOGGER.warning("No Physical RIO zones, Physical RIO outputs, Virtual RIO zones, Virtual RIO outputs, or Groups found - skipping RIO cards")
        
        target_view["cards"] = view_cards
        
        _LOGGER.warning(f"Total cards in view: {len(view_cards)}")
        _LOGGER.warning(f"Card titles: {[card.get('title', 'No title') for card in view_cards]}")
        
        try:
            await default_dashboard.async_save(config)
            _LOGGER.warning("=" * 60)
            _LOGGER.warning("✓ Successfully added cards to dashboard!")
            _LOGGER.warning("=" * 60)
        except Exception as e:
            _LOGGER.error(f"Failed to save dashboard: {e}", exc_info=True)
    
    except Exception as e:
        _LOGGER.error(f"Error in auto_add_cards: {e}", exc_info=True)