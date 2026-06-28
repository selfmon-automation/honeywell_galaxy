"""Lovelace dashboard card management for Honeywell Galaxy."""
from __future__ import annotations

import asyncio
import inspect
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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later

from .const import (
    DEVICE_TYPE_GROUPS,
    DEVICE_TYPE_PHYSICAL_RIO,
    DEVICE_TYPE_VIRTUAL_KEYPAD,
    DEVICE_TYPE_VIRTUAL_PRINTER,
    DEVICE_TYPE_VIRTUAL_RIO,
    DOMAIN,
    TOPIC_VKP,
)
from .device import get_device_type, iter_devices_with_areas

_LOGGER = logging.getLogger(__name__)

GALAXY_KEYPAD_TITLE = "Galaxy Keypad"
GALAXY_VIEW_TITLE = "Honeywell Galaxy"
GALAXY_KEYPAD_URL_PATH = "galaxy-keypad"
LEGACY_GALAXY_KEYPAD_URL_PATH = "security"
DEFAULT_CARD_SETUP_DELAY = 50
CARD_SETUP_RETRIES = (0, 45, 90)
CARD_RESCHEDULE_DELAY = 10

# Fallback Lovelace resource URLs when www/community scanning finds nothing.
BUTTON_CARD_RESOURCE_URLS = (
    "/hacsfiles/lovelace-button-card/button-card.js",
    "/hacsfiles/button-card/button-card.js",
    "/local/community/lovelace-button-card/button-card.js",
    "/local/community/button-card/button-card.js",
)
STACK_IN_CARD_RESOURCE_URLS = (
    "/hacsfiles/lovelace-stack-in-card/stack-in-card.js",
    "/hacsfiles/stack-in-card/stack-in-card.js",
    "/local/community/lovelace-stack-in-card/stack-in-card.js",
    "/local/community/stack-in-card/stack-in-card.js",
)
LOVELACE_RESOURCE_TARGETS = (
    {
        "name": "button-card",
        "filename": "button-card.js",
        "markers": ("button-card", "lovelace-button-card"),
        "static_urls": BUTTON_CARD_RESOURCE_URLS,
    },
    {
        "name": "stack-in-card",
        "filename": "stack-in-card.js",
        "markers": ("stack-in-card", "lovelace-stack-in-card"),
        "static_urls": STACK_IN_CARD_RESOURCE_URLS,
    },
)

DEVICE_TYPE_CARD_TITLES: dict[str, tuple[str, ...]] = {
    DEVICE_TYPE_VIRTUAL_PRINTER: ("Honeywell Galaxy Log",),
    DEVICE_TYPE_PHYSICAL_RIO: ("Physical RIO Inputs", "Physical RIO Outputs"),
    DEVICE_TYPE_VIRTUAL_RIO: ("Virtual RIO Zones", "Virtual RIO Outputs"),
    DEVICE_TYPE_GROUPS: ("Groups",),
}

_card_schedule_handles: dict[str, callback] = {}

DEFAULT_GALAXY_KEYPAD_DASHBOARD_ITEM = {
    "id": GALAXY_KEYPAD_URL_PATH,
    CONF_ALLOW_SINGLE_WORD: True,
    CONF_ICON: "mdi:dialpad",
    CONF_REQUIRE_ADMIN: False,
    CONF_SHOW_IN_SIDEBAR: True,
    CONF_TITLE: GALAXY_KEYPAD_TITLE,
    CONF_URL_PATH: GALAXY_KEYPAD_URL_PATH,
}


def _is_dedicated_galaxy_dashboard(dashboard_id: str | None) -> bool:
    """Return True for the integration's standalone keypad dashboard."""
    return dashboard_id in (GALAXY_KEYPAD_URL_PATH, LEGACY_GALAXY_KEYPAD_URL_PATH)


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

    show_in_sidebar = item.get(CONF_SHOW_IN_SIDEBAR, True)
    kwargs: dict[str, Any] = {
        "frontend_url_path": item[CONF_URL_PATH],
        "require_admin": item.get(CONF_REQUIRE_ADMIN, False),
        "sidebar_title": item[CONF_TITLE],
        "sidebar_icon": item.get(CONF_ICON, DEFAULT_ICON),
        "config": {"mode": MODE_STORAGE},
        "update": update,
    }

    register = frontend.async_register_built_in_panel
    params = inspect.signature(register).parameters
    if "show_in_sidebar" in params:
        kwargs["show_in_sidebar"] = show_in_sidebar
    elif "sidebar_default_visible" in params:
        kwargs["sidebar_default_visible"] = show_in_sidebar

    try:
        register(hass, "lovelace", **kwargs)
    except TypeError as err:
        _LOGGER.debug(
            "Panel registration retry without sidebar visibility args: %s", err
        )
        kwargs.pop("show_in_sidebar", None)
        kwargs.pop("sidebar_default_visible", None)
        register(hass, "lovelace", **kwargs)


def _find_galaxy_keypad_dashboard_item(collection: DashboardsCollection) -> dict | None:
    """Return the Galaxy Keypad dashboard item from the dashboards collection."""
    for url_path in (GALAXY_KEYPAD_URL_PATH, LEGACY_GALAXY_KEYPAD_URL_PATH):
        if url_path in collection.data:
            return collection.data[url_path]

    for item in collection.async_items():
        item_path = item.get(CONF_URL_PATH)
        if item_path in (GALAXY_KEYPAD_URL_PATH, LEGACY_GALAXY_KEYPAD_URL_PATH):
            return item

    return None


def _galaxy_keypad_dashboard_item() -> dict:
    """Return a minimal Galaxy Keypad dashboard item for LovelaceStorage."""
    return dict(DEFAULT_GALAXY_KEYPAD_DASHBOARD_ITEM)


async def _ensure_galaxy_keypad_dashboard_loaded(
    hass: HomeAssistant,
    lovelace_data,
    item: dict,
) -> LovelaceStorage:
    """Ensure the Galaxy Keypad dashboard is available in Lovelace data."""
    url_path = item[CONF_URL_PATH]
    dashboards = lovelace_data.dashboards
    if url_path not in dashboards:
        dashboards[url_path] = LovelaceStorage(hass, item)

    panel_exists = _panel_exists(hass, url_path)
    try:
        await _register_storage_dashboard_panel(hass, item, update=panel_exists)
    except Exception as err:
        _LOGGER.warning(
            "Could not update sidebar entry for /%s (cards can still be saved): %s",
            url_path,
            err,
        )

    return dashboards[url_path]


async def _get_or_create_galaxy_keypad_dashboard(
    hass: HomeAssistant,
    lovelace_data,
) -> tuple[str | None, LovelaceStorage | None, dict | None]:
    """Return a writable Galaxy Keypad dashboard, creating one if needed."""
    dashboards = lovelace_data.dashboards

    for url_path in (GALAXY_KEYPAD_URL_PATH, LEGACY_GALAXY_KEYPAD_URL_PATH):
        if url_path in dashboards:
            galaxy_dashboard = dashboards[url_path]
            config = await _try_load_dashboard(galaxy_dashboard)
            if config is not None:
                return url_path, galaxy_dashboard, config

    collection = DashboardsCollection(hass)
    await collection.async_load()
    item = _find_galaxy_keypad_dashboard_item(collection)

    if item is None:
        try:
            await collection.async_create_item(
                {
                    CONF_ALLOW_SINGLE_WORD: True,
                    CONF_ICON: DEFAULT_GALAXY_KEYPAD_DASHBOARD_ITEM[CONF_ICON],
                    CONF_TITLE: DEFAULT_GALAXY_KEYPAD_DASHBOARD_ITEM[CONF_TITLE],
                    CONF_URL_PATH: GALAXY_KEYPAD_URL_PATH,
                }
            )
        except HomeAssistantError as err:
            if getattr(err, "translation_key", None) == "url_already_exists":
                _LOGGER.info(
                    "Galaxy Keypad dashboard panel already registered; reusing /%s",
                    GALAXY_KEYPAD_URL_PATH,
                )
                item = _galaxy_keypad_dashboard_item()
            else:
                _LOGGER.warning("Could not create Galaxy Keypad dashboard: %s", err)
                return None, None, None
        except vol.Invalid as err:
            _LOGGER.warning("Could not create Galaxy Keypad dashboard: %s", err)
            return None, None, None
        else:
            item = _find_galaxy_keypad_dashboard_item(collection)

    if item is None:
        _LOGGER.error("Galaxy Keypad dashboard item could not be resolved")
        return None, None, None

    galaxy_dashboard = await _ensure_galaxy_keypad_dashboard_loaded(
        hass, lovelace_data, item
    )
    config = await _try_load_dashboard(galaxy_dashboard)
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
        await galaxy_dashboard.async_save(config)

    return item[CONF_URL_PATH], galaxy_dashboard, config


def _collect_entities(
    entity_registry: er.EntityRegistry, entry_id: str
) -> dict[str, Any]:
    """Collect Honeywell Galaxy entities from the entity registry."""
    return _collect_all_entities(entity_registry, entry_id)


def _empty_entity_collection() -> dict[str, Any]:
    """Return an empty entity collection structure."""
    return {
        "entities": {},
        "prio_zones": [],
        "prio_outputs": [],
        "vrio_zones": [],
        "vrio_outputs": [],
        "groups": [],
    }


def _classify_entity(
    collected: dict[str, Any], unique_id: str, entity_id: str, entry_id: str
) -> None:
    """Add a single entity into the collected structure."""
    if unique_id.endswith("_keypad_display_line1"):
        collected["entities"]["display_line1"] = entity_id
    elif unique_id.endswith("_keypad_display_line2"):
        collected["entities"]["display_line2"] = entity_id
    elif unique_id.endswith("_printer_log"):
        collected["entities"]["printer_log"] = entity_id
    elif unique_id.startswith(f"{entry_id}_prio_zone_"):
        zone_num = unique_id.replace(f"{entry_id}_prio_zone_", "")
        collected["prio_zones"].append({"entity_id": entity_id, "zone_number": zone_num})
    elif unique_id.startswith(f"{entry_id}_prio_output_"):
        output_num = unique_id.replace(f"{entry_id}_prio_output_", "")
        collected["prio_outputs"].append(
            {"entity_id": entity_id, "output_number": output_num}
        )
    elif unique_id.startswith(f"{entry_id}_vrio_output_"):
        output_num = unique_id.replace(f"{entry_id}_vrio_output_", "")
        collected["vrio_outputs"].append(
            {"entity_id": entity_id, "output_number": output_num}
        )
    elif unique_id.startswith(f"{entry_id}_vrio_zone_"):
        zone_num = unique_id.replace(f"{entry_id}_vrio_zone_", "")
        collected["vrio_zones"].append({"entity_id": entity_id, "zone_number": zone_num})
    elif unique_id.startswith(f"{entry_id}_group_"):
        group_num = unique_id.replace(f"{entry_id}_group_", "")
        collected["groups"].append({"entity_id": entity_id, "group_number": group_num})


def _collect_entities_for_device(
    entity_registry: er.EntityRegistry, entry_id: str, device_id: str
) -> dict[str, Any]:
    """Collect entities belonging to a single Honeywell Galaxy device."""
    collected = _empty_entity_collection()

    for entity_entry in er.async_entries_for_config_entry(entity_registry, entry_id):
        if entity_entry.device_id != device_id:
            continue
        unique_id = entity_entry.unique_id
        if unique_id is None:
            continue
        _classify_entity(
            collected, unique_id, entity_entry.entity_id, entry_id
        )

    return collected


def _collect_all_entities(
    entity_registry: er.EntityRegistry, entry_id: str
) -> dict[str, Any]:
    """Collect all Honeywell Galaxy entities for a config entry."""
    collected = _empty_entity_collection()

    for entity_entry in er.async_entries_for_config_entry(entity_registry, entry_id):
        unique_id = entity_entry.unique_id
        if unique_id is None:
            continue
        _classify_entity(
            collected, unique_id, entity_entry.entity_id, entry_id
        )

    return collected


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


def _tag_card(card: dict, device_type: str) -> dict:
    """Mark a generated card so it can be replaced on later updates."""
    card["galaxy_card_source"] = device_type
    return card


def _build_entity_cards(
    collected: dict[str, Any],
    printer_log: str | None,
    *,
    device_types: frozenset[str] | None = None,
) -> list[dict]:
    """Build Lovelace entity cards, optionally limited to specific device types."""
    cards: list[dict] = []
    include = device_types.__contains__ if device_types else lambda _value: True

    if printer_log and include(DEVICE_TYPE_VIRTUAL_PRINTER):
        cards.append(
            _tag_card(
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
                },
                DEVICE_TYPE_VIRTUAL_PRINTER,
            )
        )

    if collected["prio_zones"] and include(DEVICE_TYPE_PHYSICAL_RIO):
        cards.append(
            _tag_card(
                _entities_card(
                "Physical RIO Inputs",
                [
                    z["entity_id"]
                    for z in sorted(collected["prio_zones"], key=lambda x: int(x["zone_number"]))
                ],
                ),
                DEVICE_TYPE_PHYSICAL_RIO,
            )
        )

    if collected["prio_outputs"] and include(DEVICE_TYPE_PHYSICAL_RIO):
        cards.append(
            _tag_card(
                _entities_card(
                "Physical RIO Outputs",
                [
                    o["entity_id"]
                    for o in sorted(collected["prio_outputs"], key=lambda x: int(x["output_number"]))
                ],
                ),
                DEVICE_TYPE_PHYSICAL_RIO,
            )
        )

    if collected["vrio_zones"] and include(DEVICE_TYPE_VIRTUAL_RIO):
        cards.append(
            _tag_card(
                _entities_card(
                "Virtual RIO Zones",
                [
                    z["entity_id"]
                    for z in sorted(collected["vrio_zones"], key=lambda x: int(x["zone_number"]))
                ],
                show_header_toggle=False,
                ),
                DEVICE_TYPE_VIRTUAL_RIO,
            )
        )

    if collected["vrio_outputs"] and include(DEVICE_TYPE_VIRTUAL_RIO):
        cards.append(
            _tag_card(
                _entities_card(
                "Virtual RIO Outputs",
                [
                    o["entity_id"]
                    for o in sorted(collected["vrio_outputs"], key=lambda x: int(x["output_number"]))
                ],
                ),
                DEVICE_TYPE_VIRTUAL_RIO,
            )
        )

    if collected["groups"] and include(DEVICE_TYPE_GROUPS):
        cards.append(
            _tag_card(
                _entities_card(
                "Groups",
                [
                    g["entity_id"]
                    for g in sorted(collected["groups"], key=lambda x: int(x["group_number"]))
                ],
                ),
                DEVICE_TYPE_GROUPS,
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
    """Build a full-width keypad row with entity cards in columns below."""
    log_card = _card_by_title(entity_cards, "Honeywell Galaxy Log")
    zones_card = _card_by_title(entity_cards, "Physical RIO Inputs")
    outputs_card = _card_by_title(entity_cards, "Physical RIO Outputs")
    vrio_zones_card = _card_by_title(entity_cards, "Virtual RIO Zones")
    vrio_outputs_card = _card_by_title(entity_cards, "Virtual RIO Outputs")
    groups_card = _card_by_title(entity_cards, "Groups")

    def _column(*cards: dict | None) -> dict:
        return {"type": "vertical-stack", "cards": [c for c in cards if c is not None]}

    entity_columns = [
        col
        for col in (
            _column(vrio_outputs_card, groups_card),
            _column(log_card, zones_card),
            _column(outputs_card, vrio_zones_card),
        )
        if col["cards"]
    ]

    if not entity_columns:
        return keypad_card

    if len(entity_columns) == 1:
        return {"type": "vertical-stack", "cards": [keypad_card, entity_columns[0]]}

    return {
        "type": "vertical-stack",
        "cards": [
            keypad_card,
            {
                "type": "grid",
                "columns": min(3, len(entity_columns)),
                "square": False,
                "cards": entity_columns,
            },
        ],
    }


def _community_path_for_resource_url(hass: HomeAssistant, url: str) -> Path | None:
    """Map a /hacsfiles or /local/community URL to a file under www/community."""
    path = url.split("?", 1)[0]
    community = Path(hass.config.path("www")) / "community"

    if path.startswith("/hacsfiles/"):
        rel = path.removeprefix("/hacsfiles/")
        return community / rel

    if path.startswith("/local/community/"):
        rel = path.removeprefix("/local/community/")
        return community / rel

    return None


def _resource_file_exists(hass: HomeAssistant, url: str) -> bool:
    """Return True when a Lovelace resource URL points at an installed file."""
    file_path = _community_path_for_resource_url(hass, url)
    return file_path is not None and file_path.is_file()


def _discover_community_resource_urls(hass: HomeAssistant, filename: str) -> list[str]:
    """Scan www/community for an installed HACS frontend file."""
    community = Path(hass.config.path("www")) / "community"
    if not community.is_dir():
        return []

    urls: list[str] = []
    for js_path in community.rglob(filename):
        if not js_path.is_file():
            continue
        try:
            rel = js_path.relative_to(community)
        except ValueError:
            continue
        rel_posix = rel.as_posix()
        for prefix in ("/hacsfiles/", "/local/community/"):
            url = f"{prefix}{rel_posix}"
            if url not in urls:
                urls.append(url)
    return urls


def _resource_candidates(
    hass: HomeAssistant, *, filename: str, static_urls: tuple[str, ...]
) -> list[str]:
    """Return deduplicated Lovelace resource URLs, preferring installed files."""
    discovered = _discover_community_resource_urls(hass, filename)
    installed = [url for url in discovered if _resource_file_exists(hass, url)]
    ordered: list[str] = []

    for url in (*installed, *discovered, *static_urls):
        if url not in ordered:
            ordered.append(url)
    return ordered


async def _ensure_lovelace_resources(hass: HomeAssistant) -> bool:
    """Ensure button-card and stack-in-card are registered for Lovelace."""
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None:
        return False

    resources = getattr(lovelace_data, "resources", None)
    if resources is None:
        return False

    if not getattr(resources, "loaded", False):
        await resources.async_load()
        resources.loaded = True

    existing_urls = [item["url"] for item in resources.async_items()]

    def _resource_registered(markers: tuple[str, ...]) -> bool:
        for url in existing_urls:
            url_lower = url.lower()
            if any(marker in url_lower for marker in markers):
                return True
        return False

    added: list[str] = []
    missing_install: list[str] = []

    for target in LOVELACE_RESOURCE_TARGETS:
        name = target["name"]
        markers = target["markers"]
        if _resource_registered(markers):
            continue

        candidates = _resource_candidates(
            hass,
            filename=target["filename"],
            static_urls=target["static_urls"],
        )
        registered = False

        for url in candidates:
            if not _resource_file_exists(hass, url):
                continue
            try:
                await resources.async_create_item({"url": url, "type": "module"})
                existing_urls.append(url)
                added.append(url)
                registered = True
                break
            except Exception as err:
                _LOGGER.warning(
                    "Could not register Lovelace resource %s: %s", url, err
                )

        if not registered and not any(
            _resource_file_exists(hass, url) for url in candidates
        ):
            missing_install.append(name)

    if added:
        _LOGGER.info("Registered Lovelace resources: %s", ", ".join(added))

    missing = [
        target["name"]
        for target in LOVELACE_RESOURCE_TARGETS
        if not _resource_registered(target["markers"])
    ]
    if missing:
        if missing_install:
            _LOGGER.warning(
                "Missing Lovelace resources for the graphical keypad: %s. "
                "Install the missing card(s) from HACS (Frontend plugins), then "
                "use each card's HACS menu → Add to Lovelace resources, or run "
                "honeywell_galaxy.add_dashboard_cards again.",
                ", ".join(missing_install),
            )
        else:
            _LOGGER.warning(
                "Lovelace resources not registered for the graphical keypad: %s. "
                "Open Settings → Dashboards → Resources and add them, or run "
                "honeywell_galaxy.add_dashboard_cards again.",
                ", ".join(missing),
            )
        return False

    return True


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
    config.pop("strategy", None)

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
    target.pop("strategy", None)
    target.pop("sections", None)
    if target.get("type") == "sections":
        target.pop("type", None)
    config["views"] = [target]
    return target


def _apply_galaxy_layout(
    config: dict,
    target_view: dict,
    layout: dict,
    *,
    dedicated_dashboard: bool,
) -> None:
    """Write the Galaxy layout, replacing area-strategy content when needed."""
    config.pop("strategy", None)
    target_view.pop("strategy", None)
    target_view.pop("sections", None)
    if target_view.get("type") == "sections":
        target_view.pop("type", None)

    if dedicated_dashboard:
        target_view["type"] = "panel"
        target_view["cards"] = [layout]
        return

    _merge_layout_into_view(target_view, layout)


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
    if card.get("type") in ("horizontal-stack", "vertical-stack", "grid"):
        return any(
            _is_galaxy_layout_card(sub)
            for sub in card.get("cards", [])
            if isinstance(sub, dict)
        )
    return False


async def _resolve_area_dashboard_view(
    hass: HomeAssistant,
    lovelace_data,
    area_id: str,
    area_name: str,
) -> tuple[str | None, LovelaceStorage | None, dict | None, dict | None]:
    """Find or create a writable dashboard view for a device area."""
    loadable = await _iter_loadable_dashboards(lovelace_data)

    match = _find_area_view_in_dashboards(loadable, area_id, area_name)
    if match:
        dash_id, dashboard, config, view = match
        _LOGGER.info(
            "Matched area view '%s' on dashboard '%s'",
            area_name,
            dash_id or "default",
        )
        return match

    for prefer_id in ("lovelace", None):
        for dash_id, dashboard, config in loadable:
            if dash_id != prefer_id:
                continue
            view = _ensure_area_view(config, area_id, area_name)
            _LOGGER.info(
                "Created area view '%s' on dashboard '%s'",
                area_name,
                dash_id or "default",
            )
            return dash_id, dashboard, config, view

    return None, None, None, None


def _card_belongs_to_device(card: dict, device_type: str) -> bool:
    """Return True if a card was created for a specific integration device."""
    if card.get("galaxy_card_source") == device_type:
        return True
    if device_type == DEVICE_TYPE_VIRTUAL_KEYPAD and _is_galaxy_layout_card(card):
        return True
    title = card.get("title")
    if title and title in DEVICE_TYPE_CARD_TITLES.get(device_type, ()):
        return True
    if card.get("type") in ("vertical-stack", "grid", "horizontal-stack"):
        sub_cards = card.get("cards", [])
        if sub_cards and all(
            isinstance(sub, dict) and _card_belongs_to_device(sub, device_type)
            for sub in sub_cards
        ):
            return True
    return False


def _merge_device_cards_into_view(
    view: dict, cards: list[dict], device_type: str
) -> None:
    """Replace prior cards for one device type and append the new ones."""
    if _view_uses_sections(view):
        sections = view.setdefault("sections", [])
        if not sections:
            sections.append({"type": "grid", "cards": []})
        target_cards = sections[0].setdefault("cards", [])
    else:
        target_cards = view.setdefault("cards", [])

    filtered = [
        card for card in target_cards if not _card_belongs_to_device(card, device_type)
    ]
    filtered.extend(cards)

    if _view_uses_sections(view):
        sections[0]["cards"] = filtered
    else:
        view["cards"] = filtered


def _device_collection_ready(collected: dict[str, Any], device_type: str) -> bool:
    """Return True when enough entities exist to build cards for a device."""
    if device_type == DEVICE_TYPE_VIRTUAL_KEYPAD:
        entities = collected["entities"]
        return bool(entities.get("display_line1") and entities.get("display_line2"))
    if device_type == DEVICE_TYPE_VIRTUAL_PRINTER:
        return bool(collected["entities"].get("printer_log"))
    if device_type == DEVICE_TYPE_PHYSICAL_RIO:
        return bool(collected["prio_zones"] or collected["prio_outputs"])
    if device_type == DEVICE_TYPE_VIRTUAL_RIO:
        return bool(collected["vrio_zones"] or collected["vrio_outputs"])
    if device_type == DEVICE_TYPE_GROUPS:
        return bool(collected["groups"])
    return False


async def _wait_for_device_entities(
    hass: HomeAssistant,
    entry_id: str,
    device_id: str,
    device_type: str,
    *,
    timeout: int = 90,
) -> dict[str, Any]:
    """Wait for entities on a specific device before building its cards."""
    entity_registry = er.async_get(hass)

    for second in range(timeout):
        collected = _collect_entities_for_device(
            entity_registry, entry_id, device_id
        )
        if _device_collection_ready(collected, device_type):
            return collected
        if second >= 10 and device_type != DEVICE_TYPE_VIRTUAL_KEYPAD:
            return collected
        await asyncio.sleep(1)

    return _collect_entities_for_device(entity_registry, entry_id, device_id)


async def _build_device_cards(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device_type: str,
    collected: dict[str, Any],
) -> list[dict]:
    """Build Lovelace cards for a single Honeywell Galaxy device."""
    if device_type == DEVICE_TYPE_VIRTUAL_KEYPAD:
        entities = collected["entities"]
        if not entities.get("display_line1") or not entities.get("display_line2"):
            return []
        keypad_card = await _load_keypad_card(
            entry, entities["display_line1"], entities["display_line2"]
        )
        if keypad_card is None:
            return []
        return [_tag_card(keypad_card, DEVICE_TYPE_VIRTUAL_KEYPAD)]

    return _build_entity_cards(
        collected,
        collected["entities"].get("printer_log"),
        device_types=frozenset({device_type}),
    )


async def _save_cards_to_area_view(
    hass: HomeAssistant,
    lovelace_data,
    area_id: str,
    area_name: str,
    cards: list[dict],
    device_type: str,
) -> bool:
    """Merge device cards into the dashboard view for an area."""
    if not cards:
        return False

    dash_id, target_dashboard, config, target_view = (
        await _resolve_area_dashboard_view(hass, lovelace_data, area_id, area_name)
    )
    if not target_dashboard or config is None or target_view is None:
        _LOGGER.error(
            "No writable Lovelace dashboard available for area '%s'", area_name
        )
        return False

    _merge_device_cards_into_view(target_view, cards, device_type)
    await target_dashboard.async_save(config)

    view_label = target_view.get("title") or target_view.get("path") or "view"
    _LOGGER.info(
        "Galaxy cards for %s saved to dashboard '%s', view '%s'",
        device_type,
        dash_id or "default",
        view_label,
    )
    return True


async def _save_keypad_to_galaxy_dashboard(
    hass: HomeAssistant,
    lovelace_data,
    keypad_card: dict,
) -> bool:
    """Save the graphical keypad to the dedicated Galaxy Keypad dashboard."""
    dash_id, dashboard, config = await _get_or_create_galaxy_keypad_dashboard(
        hass, lovelace_data
    )
    if not dashboard or config is None:
        return False

    view = _normalize_security_dashboard_view(config)
    _apply_galaxy_layout(config, view, keypad_card, dedicated_dashboard=True)
    await dashboard.async_save(config)
    _LOGGER.info("Graphical keypad saved to /%s dashboard", dash_id)
    return True


async def _try_add_cards_for_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device_id: str,
    *,
    wait_timeout: int = 90,
) -> bool:
    """Add Lovelace cards for one Honeywell Galaxy device."""
    device_registry = dr.async_get(hass)
    device = device_registry.async_get(device_id)
    if device is None or not device.area_id:
        return False

    device_type = get_device_type(device)
    if device_type is None:
        return False

    if LOVELACE_DATA not in hass.data:
        _LOGGER.error("Lovelace not available")
        return False

    lovelace = hass.data[LOVELACE_DATA]
    if not hasattr(lovelace, "dashboards"):
        _LOGGER.error("Lovelace dashboards not available")
        return False

    collected = await _wait_for_device_entities(
        hass, entry.entry_id, device_id, device_type, timeout=wait_timeout
    )
    cards = await _build_device_cards(hass, entry, device_type, collected)
    if not cards:
        _LOGGER.warning(
            "No cards built yet for %s device on entry %s",
            device_type,
            entry.entry_id,
        )
        return False

    area_name = _area_name(hass, device.area_id)
    if area_name is None:
        return False

    saved = await _save_cards_to_area_view(
        hass,
        lovelace,
        device.area_id,
        area_name,
        cards,
        device_type,
    )

    if device_type == DEVICE_TYPE_VIRTUAL_KEYPAD:
        resources_ok = await _ensure_lovelace_resources(hass)
        keypad_saved = await _save_keypad_to_galaxy_dashboard(
            hass, lovelace, cards[0]
        )
        saved = saved or keypad_saved

        if keypad_saved:
            from homeassistant.components import persistent_notification

            resource_hint = ""
            if not resources_ok:
                resource_hint = (
                    "\n\nThe graphical keypad requires **button-card** (RomRider) and "
                    "**stack-in-card** (custom-cards) from HACS. Install any missing "
                    "plugins, add them under Settings → Dashboards → Resources, hard-"
                    "refresh the browser (Cmd+Shift+R), then run "
                    "**honeywell_galaxy.add_dashboard_cards** again."
                )

            persistent_notification.async_create(
                hass,
                (
                    f"The graphical keypad is ready. Open **{GALAXY_KEYPAD_TITLE}** in "
                    f"the left sidebar, or go to /{GALAXY_KEYPAD_URL_PATH} in your "
                    "browser."
                    f"{resource_hint}"
                ),
                title="Honeywell Galaxy",
                notification_id=f"{DOMAIN}_dashboard_cards",
            )

    return saved


async def _try_add_full_dashboard(
    hass: HomeAssistant, entry: ConfigEntry, *, wait_timeout: int = 90
) -> bool:
    """Rebuild the full Galaxy Keypad dashboard with every entity group."""
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

    resources_ok = await _ensure_lovelace_resources(hass)

    lovelace = hass.data[LOVELACE_DATA]
    if not hasattr(lovelace, "dashboards"):
        _LOGGER.error("Lovelace dashboards not available")
        return False

    dash_id, target_dashboard, config = await _get_or_create_galaxy_keypad_dashboard(
        hass, lovelace
    )
    if not target_dashboard or config is None:
        _LOGGER.error("Galaxy Keypad dashboard is not available")
        return False

    entity_cards = _build_entity_cards(collected, entities.get("printer_log"))
    layout = _build_three_column_layout(
        _tag_card(keypad_card, DEVICE_TYPE_VIRTUAL_KEYPAD), entity_cards
    )
    view = _normalize_security_dashboard_view(config)
    _apply_galaxy_layout(config, view, layout, dedicated_dashboard=True)
    await target_dashboard.async_save(config)

    resource_hint = ""
    if not resources_ok:
        resource_hint = (
            "\n\nThe graphical keypad requires **button-card** and **stack-in-card** "
            "from HACS. Add them under Settings → Dashboards → Resources if needed."
        )

    from homeassistant.components import persistent_notification

    persistent_notification.async_create(
        hass,
        (
            f"Full Galaxy dashboard rebuilt on **{GALAXY_KEYPAD_TITLE}** "
            f"(/{dash_id}).{resource_hint}"
        ),
        title="Honeywell Galaxy",
        notification_id=f"{DOMAIN}_dashboard_cards",
    )

    _LOGGER.warning(
        "Full Galaxy dashboard saved to /%s (%s zones, %s groups)",
        dash_id,
        len(collected["prio_zones"]),
        len(collected["groups"]),
    )
    return True


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
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    device_id: str | None = None,
    delay_seconds: int = CARD_RESCHEDULE_DELAY,
) -> None:
    """Debounce dashboard card creation after a device area assignment changes."""
    handle_key = f"{entry.entry_id}:{device_id or 'all'}"
    if handle_key in _card_schedule_handles:
        _card_schedule_handles[handle_key]()

    @callback
    def _run(_now) -> None:
        _card_schedule_handles.pop(handle_key, None)
        hass.async_create_task(
            auto_add_cards(hass, entry, delay_seconds=0, device_id=device_id)
        )

    _card_schedule_handles[handle_key] = async_call_later(hass, delay_seconds, _run)


async def auto_add_cards(
    hass: HomeAssistant,
    entry: ConfigEntry,
    delay_seconds: int = DEFAULT_CARD_SETUP_DELAY,
    *,
    device_id: str | None = None,
    full_dashboard: bool = False,
) -> None:
    """Add Galaxy Lovelace cards for assigned devices."""
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

            wait_timeout = 90 if attempt == 0 else 10

            if full_dashboard:
                if await _try_add_full_dashboard(
                    hass, entry, wait_timeout=wait_timeout
                ):
                    return
                continue

            if device_id:
                if await _try_add_cards_for_device(
                    hass, entry, device_id, wait_timeout=wait_timeout
                ):
                    return
                continue

            devices = iter_devices_with_areas(hass, entry)
            if not devices:
                if attempt == len(CARD_SETUP_RETRIES) - 1:
                    _LOGGER.warning(
                        "No Honeywell Galaxy devices have an area assigned yet. "
                        "Assign an area on each device you want on a dashboard, then "
                        "run honeywell_galaxy.add_dashboard_cards."
                    )
                continue

            results: list[bool] = []
            for device in devices:
                results.append(
                    await _try_add_cards_for_device(
                        hass, entry, device.id, wait_timeout=wait_timeout
                    )
                )
            if any(results):
                return

        _LOGGER.error(
            "Galaxy dashboard cards could not be created. "
            "Run service honeywell_galaxy.add_dashboard_cards to retry."
        )
    except Exception as err:
        _LOGGER.error("Error adding Galaxy dashboard cards: %s", err, exc_info=True)
