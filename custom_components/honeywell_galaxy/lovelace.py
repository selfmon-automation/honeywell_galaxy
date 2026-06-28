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
from homeassistant.components.lovelace.dashboard import DashboardsCollection, LovelaceStorage
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN, TOPIC_VKP
from .device import get_entry_area_id

_LOGGER = logging.getLogger(__name__)

GALAXY_KEYPAD_TITLE = "Galaxy Keypad"
GALAXY_VIEW_TITLE = "Honeywell Galaxy"
SECURITY_URL_PATH = "security"
DEFAULT_CARD_SETUP_DELAY = 50
CARD_SETUP_RETRIES = (0, 45, 90)
CARD_RESCHEDULE_DELAY = 10

_card_schedule_handles: dict[str, callback] = {}

DEFAULT_SECURITY_DASHBOARD_ITEM = {
    "id": SECURITY_URL_PATH,
    CONF_ALLOW_SINGLE_WORD: True,
    CONF_ICON: "mdi:shield-home",
    CONF_REQUIRE_ADMIN: False,
    CONF_SHOW_IN_SIDEBAR: True,
    CONF_TITLE: "Security",
    CONF_URL_PATH: SECURITY_URL_PATH,
}


@callback
def _panel_exists(hass: HomeAssistant, url_path: str) -> bool:
    """Return whether a frontend panel is already registered."""
    from homeassistant.components import frontend

    if hasattr(frontend, "async_panel_exists"):
        return frontend.async_panel_exists(hass, url_path)

    panels_key = getattr(frontend, "DATA_PANELS", "frontend_panels")
    panels = hass.data.get(panels_key, {})
    return url_path in panels


async def _try_load_dashboard(dashboard) -> dict | None:
    """Load a dashboard config, returning None if unavailable."""
    try:
        return await dashboard.async_load(force=False)
    except ConfigNotFound:
        return None


async def _register_storage_dashboard_panel(
    hass: HomeAssistant, item: dict, *, update: bool = False
) -> None:
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
        update=update,
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

    panel_exists = _panel_exists(hass, SECURITY_URL_PATH)
    await _register_storage_dashboard_panel(hass, item, update=panel_exists)

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
        config = {
            "views": [
                {
                    "title": GALAXY_VIEW_TITLE,
                    "path": "galaxy",
                    "cards": [],
                }
            ]
        }
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


def _area_name(hass: HomeAssistant, area_id: str) -> str | None:
    """Return the friendly name for an area id."""
    area = ar.async_get(hass).async_get_area(area_id)
    return area.name if area else None


def _dashboard_has_strategy(config: dict) -> bool:
    """Return True if the dashboard uses a strategy (not programmatically editable)."""
    return "strategy" in config


def _view_uses_sections(view: dict) -> bool:
    """Return True if the view stores cards in sections rather than at view root."""
    return view.get("type") == "sections" or bool(view.get("sections"))


async def _iter_loadable_dashboards(
    lovelace_data,
) -> list[tuple[str | None, LovelaceStorage, dict]]:
    """Return storage dashboards that can be loaded and saved."""
    loadable: list[tuple[str | None, LovelaceStorage, dict]] = []
    for dash_id, dashboard in lovelace_data.dashboards.items():
        if dash_id == "map" or dashboard.mode != MODE_STORAGE:
            continue
        config = await _try_load_dashboard(dashboard)
        if config is None or _dashboard_has_strategy(config):
            continue
        loadable.append((dash_id, dashboard, config))
    return loadable


def _card_references_area(card: dict, area_id: str) -> bool:
    """Return True if a card represents the given area."""
    if card.get("type") == "area" and card.get("area") == area_id:
        return True

    for key in ("cards", "sections"):
        for item in card.get(key, []):
            if isinstance(item, dict):
                if key == "sections":
                    for section_card in item.get("cards", []):
                        if isinstance(section_card, dict) and _card_references_area(
                            section_card, area_id
                        ):
                            return True
                elif _card_references_area(item, area_id):
                    return True
    return False


def _view_matches_area(
    view: dict, area_id: str, area_name: str | None
) -> bool:
    """Return True if a Lovelace view belongs to the given area."""
    if view.get("path") == area_id:
        return True
    if area_name and view.get("title", "").casefold() == area_name.casefold():
        return True
    return any(
        isinstance(card, dict) and _card_references_area(card, area_id)
        for card in view.get("cards", [])
    )


def _find_view_by_title(config: dict, title: str) -> dict | None:
    """Return the first view whose title matches case-insensitively."""
    for view in config.get("views", []):
        if isinstance(view, dict) and view.get("title", "").casefold() == title.casefold():
            return view
    return None


def _first_view(config: dict) -> dict | None:
    """Return the first view in a dashboard config."""
    views = config.get("views", [])
    if views and isinstance(views[0], dict):
        return views[0]
    return None


def _ensure_area_view(
    config: dict, area_id: str, area_name: str
) -> dict:
    """Return an existing area view or append one to the dashboard."""
    views = config.setdefault("views", [])
    for view in views:
        if isinstance(view, dict) and _view_matches_area(view, area_id, area_name):
            return view

    view = {"title": area_name, "path": area_id, "cards": []}
    views.append(view)
    return view


def _find_area_view_in_dashboards(
    loadable: list[tuple[str | None, LovelaceStorage, dict]],
    area_id: str,
    area_name: str,
) -> tuple[str | None, LovelaceStorage, dict, dict] | None:
    """Find a dashboard view that matches the assigned device area."""
    preferred_ids: list[str | None] = []
    for dash_id, _, _ in loadable:
        if dash_id in (None, "lovelace") and dash_id not in preferred_ids:
            preferred_ids.insert(0, dash_id)
        elif dash_id not in preferred_ids:
            preferred_ids.append(dash_id)

    for dash_id in preferred_ids:
        for candidate_id, dashboard, config in loadable:
            if candidate_id != dash_id:
                continue
            for view in config.get("views", []):
                if isinstance(view, dict) and _view_matches_area(
                    view, area_id, area_name
                ):
                    return candidate_id, dashboard, config, view
    return None


def _find_dashboard_by_substring(
    loadable: list[tuple[str | None, LovelaceStorage, dict]],
    search: str,
) -> tuple[str | None, LovelaceStorage, dict, dict] | None:
    """Find a dashboard or view containing the search substring."""
    search_lower = search.casefold()
    for dash_id, dashboard, config in loadable:
        if dash_id and search_lower in str(dash_id).casefold():
            view = _find_view_by_title(config, "security") or _first_view(config)
            if view is not None:
                return dash_id, dashboard, config, view

        for view in config.get("views", []):
            if not isinstance(view, dict):
                continue
            if search_lower in view.get("title", "").casefold():
                return dash_id, dashboard, config, view
    return None


def _normalize_security_dashboard_view(config: dict) -> dict:
    """Collapse duplicate views on /security into one canonical tab."""
    views = [view for view in config.get("views", []) if isinstance(view, dict)]
    target: dict | None = None

    for view in views:
        title = view.get("title", "").casefold()
        if title in {
            GALAXY_VIEW_TITLE.casefold(),
            "security",
            "galaxy",
            "honeywell galaxy",
        }:
            target = view
            break

    if target is None:
        target = {"title": GALAXY_VIEW_TITLE, "path": "galaxy", "cards": []}

    target["title"] = GALAXY_VIEW_TITLE
    target.setdefault("path", "galaxy")
    config["views"] = [target]
    return target


async def _resolve_dashboard_and_view(
    hass: HomeAssistant,
    lovelace_data,
    entry: ConfigEntry,
) -> tuple[str | None, LovelaceStorage | None, dict | None, dict | None]:
    """Find a writable dashboard view for the integration's assigned area."""
    area_id = get_entry_area_id(hass, entry)
    area_name = _area_name(hass, area_id) if area_id else None
    loadable = await _iter_loadable_dashboards(lovelace_data)

    _LOGGER.info(
        "Resolving Galaxy dashboard (area=%s, loadable_dashboards=%s)",
        area_name or "none",
        [dash_id or "default" for dash_id, _, _ in loadable],
    )

    dash_id, dashboard, config = await _get_or_create_security_dashboard(
        hass, lovelace_data
    )
    if dashboard and config:
        view = _normalize_security_dashboard_view(config)
        _LOGGER.info(
            "Using dedicated /%s dashboard for Galaxy cards",
            SECURITY_URL_PATH,
        )
        return dash_id, dashboard, config, view

    if area_id and area_name:
        match = _find_area_view_in_dashboards(loadable, area_id, area_name)
        if match:
            dash_id, dashboard, config, view = match
            _LOGGER.info(
                "Matched area view '%s' on dashboard '%s'",
                area_name,
                dash_id or "default",
            )
            return match

    for substring in ("selfmon",):
        match = _find_dashboard_by_substring(loadable, substring)
        if match:
            dash_id, _, _, view = match
            _LOGGER.info(
                "Using '%s' dashboard/view match on '%s'",
                substring,
                dash_id or "default",
            )
            return match

    for dash_id, dashboard, config in loadable:
        view = _first_view(config)
        if view is not None:
            return dash_id, dashboard, config, view

    return None, None, None, None


def _is_galaxy_layout_card(card: dict) -> bool:
    """Return True if a card is part of a previous Galaxy dashboard layout."""
    if card.get("title") == GALAXY_KEYPAD_TITLE:
        return True
    if card.get("type") == "custom:stack-in-card":
        return any(
            sub.get("name") == "VKPDisplay"
            for sub in card.get("cards", [])
            if isinstance(sub, dict)
        )
    if card.get("type") in ("horizontal-stack", "vertical-stack"):
        return any(
            _is_galaxy_layout_card(sub)
            for sub in card.get("cards", [])
            if isinstance(sub, dict)
        )
    return False


def _merge_layout_into_view(view: dict, layout: dict) -> None:
    """Replace any previous Galaxy layout and prepend the new one."""
    if _view_uses_sections(view):
        sections = view.setdefault("sections", [])
        if not sections:
            sections.append({"type": "grid", "cards": []})
        first_section = sections[0]
        cards = first_section.setdefault("cards", [])
        first_section["cards"] = [
            card for card in cards if not _is_galaxy_layout_card(card)
        ]
        first_section["cards"].insert(0, layout)
        return

    cards = view.setdefault("cards", [])
    view["cards"] = [card for card in cards if not _is_galaxy_layout_card(card)]
    view["cards"].insert(0, layout)


@callback
def schedule_add_cards(
    hass: HomeAssistant, entry: ConfigEntry, delay_seconds: int = CARD_RESCHEDULE_DELAY
) -> None:
    """Debounce dashboard card creation after area assignment changes."""
    entry_id = entry.entry_id
    if entry_id in _card_schedule_handles:
        _card_schedule_handles[entry_id]()

    @callback
    def _run(_now) -> None:
        _card_schedule_handles.pop(entry_id, None)
        hass.async_create_task(auto_add_cards(hass, entry, delay_seconds=0))

    _card_schedule_handles[entry_id] = async_call_later(hass, delay_seconds, _run)


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

    _dashboard_id, target_dashboard, config, target_view = (
        await _resolve_dashboard_and_view(hass, lovelace, entry)
    )
    if not target_dashboard or config is None or target_view is None:
        area_id = get_entry_area_id(hass, entry)
        if area_id is None:
            _LOGGER.warning(
                "No area assigned to Honeywell Galaxy devices yet. "
                "Assign an area in device settings, then run "
                "honeywell_galaxy.add_dashboard_cards."
            )
        else:
            _LOGGER.error(
                "No writable Lovelace dashboard available for Galaxy cards"
            )
        return False

    entity_cards = _build_entity_cards(collected, entities.get("printer_log"))
    layout = _build_three_column_layout(keypad_card, entity_cards)
    _merge_layout_into_view(target_view, layout)

    await target_dashboard.async_save(config)

    if _dashboard_id == SECURITY_URL_PATH:
        from homeassistant.components import persistent_notification

        persistent_notification.async_create(
            hass,
            (
                "The graphical Galaxy keypad has been added to the Security dashboard. "
                f"Open /{SECURITY_URL_PATH} in your browser, or look for "
                "'Security' in the left sidebar after a page refresh."
            ),
            title="Honeywell Galaxy",
            notification_id=f"{DOMAIN}_dashboard_cards",
        )

    view_label = target_view.get("title") or target_view.get("path") or "view"
    dashboard_label = _dashboard_id or "default"
    if _dashboard_id == SECURITY_URL_PATH:
        location_hint = (
            f"Open Security in the left sidebar (/{SECURITY_URL_PATH})"
        )
    else:
        location_hint = (
            f"Open dashboard '{dashboard_label}' and select the '{view_label}' tab"
        )
    _LOGGER.warning(
        "Galaxy dashboard cards saved to dashboard '%s', view '%s' "
        "(%s zones, %s groups). %s",
        dashboard_label,
        view_label,
        len(collected["prio_zones"]),
        len(collected["groups"]),
        location_hint,
    )
    return True


async def auto_add_cards(
    hass: HomeAssistant,
    entry: ConfigEntry,
    delay_seconds: int = DEFAULT_CARD_SETUP_DELAY,
) -> None:
    """Add Galaxy Lovelace cards to the dashboard view for the assigned area."""
    if delay_seconds:
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
