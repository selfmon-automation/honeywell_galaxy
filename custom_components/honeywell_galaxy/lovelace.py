"""Lovelace dashboard card management for Honeywell Galaxy."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml
import voluptuous as vol

from homeassistant.components.lovelace.const import (
    CONF_ALLOW_SINGLE_WORD,
    CONF_ICON,
    CONF_REQUIRE_ADMIN,
    CONF_SHOW_IN_SIDEBAR,
    CONF_TITLE,
    CONF_URL_PATH,
    DEFAULT_ICON,
    LOVELACE_DATA,
    MODE_STORAGE,
    ConfigNotFound,
)
from homeassistant.components.frontend import async_panel_exists
from homeassistant.components.lovelace.dashboard import DashboardsCollection, LovelaceStorage
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, TOPIC_VKP

_LOGGER = logging.getLogger(__name__)

SECURITY_URL_PATH = "security"
DEFAULT_CARD_SETUP_DELAY = 50
CARD_SETUP_RETRIES = (0, 45, 90)

DEFAULT_SECURITY_DASHBOARD_ITEM = {
    "id": SECURITY_URL_PATH,
    CONF_ALLOW_SINGLE_WORD: True,
    CONF_ICON: "mdi:shield-home",
    CONF_REQUIRE_ADMIN: False,
    CONF_SHOW_IN_SIDEBAR: True,
    CONF_TITLE: "Security",
    CONF_URL_PATH: SECURITY_URL_PATH,
}


async def _try_load_dashboard(dashboard) -> dict | None:
    """Load a dashboard config, returning None if unavailable."""
    try:
        return await dashboard.async_load(force=False)
    except ConfigNotFound:
        return None


async def _register_storage_dashboard_panel(hass: HomeAssistant, item: dict) -> None:
    """Register a storage-mode dashboard in the frontend."""
    from homeassistant.components import frontend

    frontend.async_register_built_in_panel(
        hass,
        "lovelace",
        frontend_url_path=item[CONF_URL_PATH],
        require_admin=item.get(CONF_REQUIRE_ADMIN, False),
        show_in_sidebar=item.get(CONF_SHOW_IN_SIDEBAR, True),
        sidebar_title=item[CONF_TITLE],
        sidebar_icon=item.get(CONF_ICON, DEFAULT_ICON),
        config={"mode": MODE_STORAGE},
        update=False,
    )


def _find_security_dashboard_item(collection: DashboardsCollection) -> dict | None:
    """Return the Security dashboard item from the dashboards collection."""
    if SECURITY_URL_PATH in collection.data:
        return collection.data[SECURITY_URL_PATH]

    for item in collection.async_items():
        if item.get(CONF_URL_PATH) == SECURITY_URL_PATH:
            return item

    return None


def _security_dashboard_item() -> dict:
    """Return a minimal Security dashboard item for LovelaceStorage."""
    return dict(DEFAULT_SECURITY_DASHBOARD_ITEM)


async def _ensure_security_dashboard_loaded(
    hass: HomeAssistant,
    lovelace_data,
    item: dict,
) -> LovelaceStorage:
    """Ensure the Security dashboard is available in Lovelace data."""
    dashboards = lovelace_data.dashboards
    if SECURITY_URL_PATH not in dashboards:
        dashboards[SECURITY_URL_PATH] = LovelaceStorage(hass, item)

    if not async_panel_exists(hass, SECURITY_URL_PATH):
        await _register_storage_dashboard_panel(hass, item)

    return dashboards[SECURITY_URL_PATH]


async def _get_or_create_security_dashboard(
    hass: HomeAssistant,
    lovelace_data,
) -> tuple[str | None, LovelaceStorage | None, dict | None]:
    """Return a writable Security dashboard, creating one if needed."""
    dashboards = lovelace_data.dashboards

    if SECURITY_URL_PATH in dashboards:
        security_dashboard = dashboards[SECURITY_URL_PATH]
        config = await _try_load_dashboard(security_dashboard)
        if config is not None:
            return SECURITY_URL_PATH, security_dashboard, config

    collection = DashboardsCollection(hass)
    await collection.async_load()
    item = _find_security_dashboard_item(collection)

    if item is None:
        try:
            await collection.async_create_item(
                {
                    CONF_ALLOW_SINGLE_WORD: True,
                    CONF_ICON: DEFAULT_SECURITY_DASHBOARD_ITEM[CONF_ICON],
                    CONF_TITLE: DEFAULT_SECURITY_DASHBOARD_ITEM[CONF_TITLE],
                    CONF_URL_PATH: SECURITY_URL_PATH,
                }
            )
        except HomeAssistantError as err:
            if getattr(err, "translation_key", None) == "url_already_exists":
                _LOGGER.info(
                    "Security dashboard panel already registered; reusing /%s",
                    SECURITY_URL_PATH,
                )
                item = _security_dashboard_item()
            else:
                _LOGGER.warning("Could not create security dashboard: %s", err)
                return None, None, None
        except vol.Invalid as err:
            _LOGGER.warning("Could not create security dashboard: %s", err)
            return None, None, None
        else:
            item = _find_security_dashboard_item(collection)

    if item is None:
        _LOGGER.error("Security dashboard item could not be resolved")
        return None, None, None

    security_dashboard = await _ensure_security_dashboard_loaded(
        hass, lovelace_data, item
    )
    config = await _try_load_dashboard(security_dashboard)
    if config is None:
        config = {"views": [{"title": "Security", "cards": []}]}
        await security_dashboard.async_save(config)

    return SECURITY_URL_PATH, security_dashboard, config


def _collect_entities(
    entity_registry: er.EntityRegistry, entry_id: str
) -> dict[str, Any]:
    """Collect Honeywell Galaxy entities from the entity registry."""
    entities: dict[str, str] = {}
    prio_zones: list[dict[str, str]] = []
    prio_outputs: list[dict[str, str]] = []
    vrio_zones: list[dict[str, str]] = []
    vrio_outputs: list[dict[str, str]] = []
    groups: list[dict[str, str]] = []

    for entity_entry in er.async_entries_for_config_entry(entity_registry, entry_id):
        unique_id = entity_entry.unique_id
        entity_id = entity_entry.entity_id

        if unique_id.endswith("_keypad_display_line1"):
            entities["display_line1"] = entity_id
        elif unique_id.endswith("_keypad_display_line2"):
            entities["display_line2"] = entity_id
        elif unique_id.endswith("_printer_log"):
            entities["printer_log"] = entity_id
        elif unique_id.startswith(f"{entry_id}_prio_zone_"):
            zone_num = unique_id.replace(f"{entry_id}_prio_zone_", "")
            prio_zones.append({"entity_id": entity_id, "zone_number": zone_num})
        elif unique_id.startswith(f"{entry_id}_prio_output_"):
            output_num = unique_id.replace(f"{entry_id}_prio_output_", "")
            prio_outputs.append({"entity_id": entity_id, "output_number": output_num})
        elif unique_id.startswith(f"{entry_id}_vrio_output_"):
            output_num = unique_id.replace(f"{entry_id}_vrio_output_", "")
            vrio_outputs.append({"entity_id": entity_id, "output_number": output_num})
        elif unique_id.startswith(f"{entry_id}_vrio_zone_"):
            zone_num = unique_id.replace(f"{entry_id}_vrio_zone_", "")
            vrio_zones.append({"entity_id": entity_id, "zone_number": zone_num})
        elif unique_id.startswith(f"{entry_id}_group_"):
            group_num = unique_id.replace(f"{entry_id}_group_", "")
            groups.append({"entity_id": entity_id, "group_number": group_num})

    return {
        "entities": entities,
        "prio_zones": prio_zones,
        "prio_outputs": prio_outputs,
        "vrio_zones": vrio_zones,
        "vrio_outputs": vrio_outputs,
        "groups": groups,
    }


async def _wait_for_entities(
    hass: HomeAssistant, entry_id: str, timeout: int = 90
) -> dict[str, Any]:
    """Wait for keypad display entities and MQTT discovery before building cards."""
    entity_registry = er.async_get(hass)

    for second in range(timeout):
        collected = _collect_entities(entity_registry, entry_id)
        entities = collected["entities"]
        if not entities.get("display_line1") or not entities.get("display_line2"):
            await asyncio.sleep(1)
            continue

        discovered = (
            collected["prio_zones"]
            or collected["prio_outputs"]
            or collected["groups"]
            or collected["vrio_zones"]
            or collected["vrio_outputs"]
        )
        if discovered or second >= 60:
            _LOGGER.info(
                "Entity collection ready after %ss: %s zones, %s groups",
                second,
                len(collected["prio_zones"]),
                len(collected["groups"]),
            )
            return collected
        await asyncio.sleep(1)

    return _collect_entities(entity_registry, entry_id)


async def _load_keypad_card(
    entry: ConfigEntry, display_line1: str, display_line2: str
) -> dict | None:
    """Load and populate the Galaxy Keypad card template."""
    vmodid = entry.data.get("vmodid", "")
    mqtt_topic = f"{TOPIC_VKP.format(vmodid=vmodid)}/key"
    template_path = Path(__file__).parent / "keypad_card_template.yaml"

    try:
        loop = asyncio.get_event_loop()
        template_content = await loop.run_in_executor(
            None, lambda: template_path.read_text(encoding="utf-8")
        )
        replacements = {
            "XXXXXX_DISPLAY_LINE_1": display_line1,
            "XXXXXX_DISPLAY_LINE_2": display_line2,
            "XXXXXX_MQTT_TOPIC": mqtt_topic,
        }
        for placeholder, value in replacements.items():
            template_content = template_content.replace(placeholder, value)
        return yaml.safe_load(template_content)
    except Exception as err:
        _LOGGER.error("Failed to load keypad card template: %s", err, exc_info=True)
        return None


def _entities_card(title: str, entity_ids: list[str], **kwargs: Any) -> dict:
    """Build a standard entities card."""
    card: dict[str, Any] = {
        "type": "entities",
        "title": title,
        "entities": entity_ids,
    }
    card.update(kwargs)
    return card


def _build_entity_cards(collected: dict[str, Any], printer_log: str | None) -> list[dict]:
    """Build individual Lovelace cards for all entity groups."""
    cards: list[dict] = []

    if printer_log:
        cards.append(
            {
                "type": "markdown",
                "title": "Honeywell Galaxy Log",
                "content": (
                    f"```\n{{{{ (state_attr('{printer_log}', 'log_lines') or []) "
                    f"| join('\\n') }}}}\n```"
                ),
                "card_mod": {
                    "style": (
                        "ha-card { background: #f9f9f9; font-family: monospace; "
                        "font-size: 12px; max-height: 500px; overflow-y: auto; } "
                        ".markdown { white-space: pre-wrap; }"
                    )
                },
            }
        )

    if collected["prio_zones"]:
        cards.append(
            _entities_card(
                "Physical RIO Inputs",
                [
                    z["entity_id"]
                    for z in sorted(collected["prio_zones"], key=lambda x: int(x["zone_number"]))
                ],
            )
        )

    if collected["prio_outputs"]:
        cards.append(
            _entities_card(
                "Physical RIO Outputs",
                [
                    o["entity_id"]
                    for o in sorted(collected["prio_outputs"], key=lambda x: int(x["output_number"]))
                ],
            )
        )

    if collected["vrio_zones"]:
        cards.append(
            _entities_card(
                "Virtual RIO Zones",
                [
                    z["entity_id"]
                    for z in sorted(collected["vrio_zones"], key=lambda x: int(x["zone_number"]))
                ],
                show_header_toggle=False,
            )
        )

    if collected["vrio_outputs"]:
        cards.append(
            _entities_card(
                "Virtual RIO Outputs",
                [
                    o["entity_id"]
                    for o in sorted(collected["vrio_outputs"], key=lambda x: int(x["output_number"]))
                ],
            )
        )

    if collected["groups"]:
        cards.append(
            _entities_card(
                "Groups",
                [
                    g["entity_id"]
                    for g in sorted(collected["groups"], key=lambda x: int(x["group_number"]))
                ],
            )
        )

    return cards


def _card_by_title(cards: list[dict], title: str) -> dict | None:
    """Return a card dict by title."""
    for card in cards:
        if card.get("title") == title:
            return card
    return None


def _build_three_column_layout(
    keypad_card: dict, entity_cards: list[dict]
) -> dict:
    """Build a three-column layout matching the original Galaxy dashboard."""
    log_card = _card_by_title(entity_cards, "Honeywell Galaxy Log")
    zones_card = _card_by_title(entity_cards, "Physical RIO Inputs")
    outputs_card = _card_by_title(entity_cards, "Physical RIO Outputs")
    vrio_zones_card = _card_by_title(entity_cards, "Virtual RIO Zones")
    vrio_outputs_card = _card_by_title(entity_cards, "Virtual RIO Outputs")
    groups_card = _card_by_title(entity_cards, "Groups")

    def _column(*cards: dict | None) -> dict:
        return {"type": "vertical-stack", "cards": [c for c in cards if c is not None]}

    columns = [
        _column(keypad_card, vrio_outputs_card, groups_card),
        _column(log_card, zones_card),
        _column(outputs_card, vrio_zones_card),
    ]
    columns = [col for col in columns if col["cards"]]

    if len(columns) == 1:
        return columns[0]
    return {"type": "horizontal-stack", "cards": columns}


async def _resolve_dashboard(
    hass: HomeAssistant, lovelace_data
) -> tuple[str | None, LovelaceStorage | None, dict | None]:
    """Always use the dedicated Security dashboard at /security."""
    return await _get_or_create_security_dashboard(hass, lovelace_data)


def _resolve_security_view(
    config: dict,
) -> dict:
    """Return the Security view on the Security dashboard."""
    views = config.setdefault("views", [])

    for view in views:
        if isinstance(view, dict) and view.get("title", "").lower() == "security":
            return view

    if views and isinstance(views[0], dict):
        views[0]["title"] = "Security"
        views[0].setdefault("cards", [])
        return views[0]

    view = {"title": "Security", "path": "default", "cards": []}
    views.append(view)
    return view


async def _try_add_cards(
    hass: HomeAssistant, entry: ConfigEntry, *, wait_timeout: int = 90
) -> bool:
    """Attempt to create Galaxy Lovelace cards. Returns True on success."""
    collected = await _wait_for_entities(hass, entry.entry_id, timeout=wait_timeout)
    entities = collected["entities"]

    if not entities.get("display_line1") or not entities.get("display_line2"):
        _LOGGER.warning(
            "Keypad display entities not found yet for entry %s", entry.entry_id
        )
        return False

    keypad_card = await _load_keypad_card(
        entry, entities["display_line1"], entities["display_line2"]
    )
    if keypad_card is None:
        return False

    if LOVELACE_DATA not in hass.data:
        _LOGGER.error("Lovelace not available")
        return False

    lovelace = hass.data[LOVELACE_DATA]
    if not hasattr(lovelace, "dashboards"):
        _LOGGER.error("Lovelace dashboards not available")
        return False

    _dashboard_id, target_dashboard, config = await _resolve_dashboard(
        hass, lovelace
    )
    if not target_dashboard or config is None:
        _LOGGER.error("No writable Security dashboard available for Galaxy cards")
        return False

    target_view = _resolve_security_view(config)
    entity_cards = _build_entity_cards(collected, entities.get("printer_log"))
    layout = _build_three_column_layout(keypad_card, entity_cards)
    target_view["cards"] = [layout]

    await target_dashboard.async_save(config)
    _LOGGER.warning(
        "Galaxy dashboard cards saved to /security (%s zones, %s groups). "
        "Open the Security item in the sidebar to view the graphical keypad.",
        len(collected["prio_zones"]),
        len(collected["groups"]),
    )
    return True


async def auto_add_cards(
    hass: HomeAssistant,
    entry: ConfigEntry,
    delay_seconds: int = DEFAULT_CARD_SETUP_DELAY,
) -> None:
    """Add Galaxy Lovelace cards to the Security dashboard."""
    _LOGGER.info("Galaxy dashboard cards scheduled in %s seconds", delay_seconds)
    await asyncio.sleep(delay_seconds)

    try:
        for attempt, retry_delay in enumerate(CARD_SETUP_RETRIES):
            if retry_delay and attempt > 0:
                _LOGGER.info(
                    "Retrying Galaxy dashboard cards (attempt %s)", attempt + 1
                )
                await asyncio.sleep(retry_delay)

            if await _try_add_cards(
                hass, entry, wait_timeout=90 if attempt == 0 else 10
            ):
                return

        _LOGGER.error(
            "Galaxy dashboard cards could not be created. "
            "Run service honeywell_galaxy.add_dashboard_cards to retry."
        )
    except Exception as err:
        _LOGGER.error("Error adding Galaxy dashboard cards: %s", err, exc_info=True)
