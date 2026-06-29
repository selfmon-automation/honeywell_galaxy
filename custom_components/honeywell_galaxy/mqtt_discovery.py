"""Shared MQTT topic discovery helpers."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from .const import (
    DISCOVERY_IDLE_SECONDS,
    DISCOVERY_MAX_SECONDS,
    DISCOVERY_POLL_INTERVAL,
    MQTT_CONNECT_MAX_SECONDS,
)
from .coordinator import GalaxyCoordinator

_LOGGER = logging.getLogger(__name__)


async def wait_for_mqtt_connected(coordinator: GalaxyCoordinator) -> bool:
    """Wait briefly for the coordinator MQTT client to connect."""
    if coordinator.connected:
        return True

    _LOGGER.debug("MQTT not connected yet, waiting up to %ss", MQTT_CONNECT_MAX_SECONDS)
    for _ in range(MQTT_CONNECT_MAX_SECONDS):
        await asyncio.sleep(1)
        if coordinator.connected:
            return True

    _LOGGER.error(
        "MQTT not connected after %s seconds, skipping discovery",
        MQTT_CONNECT_MAX_SECONDS,
    )
    return False


async def _wait_for_discovery_idle(
    *,
    has_items: Callable[[], bool],
    last_activity: Callable[[], float],
) -> None:
    """Stop once discovery goes quiet or the max wait is reached."""
    loop = asyncio.get_running_loop()
    started = loop.time()
    deadline = started + DISCOVERY_MAX_SECONDS

    while loop.time() < deadline:
        if has_items() and (loop.time() - last_activity()) >= DISCOVERY_IDLE_SECONDS:
            return
        await asyncio.sleep(DISCOVERY_POLL_INTERVAL)


async def discover_mqtt_numeric_ids(
    coordinator: GalaxyCoordinator,
    discovery_topic: str,
    *,
    label: str,
) -> set[int]:
    """Discover numeric IDs published under an MQTT wildcard topic."""
    discovered: set[int] = set()
    loop = asyncio.get_running_loop()
    activity = {"at": loop.time()}

    def discovery_handler(topic: str, payload: str) -> None:
        try:
            item_id = int(topic.split("/")[-1])
        except (ValueError, IndexError):
            _LOGGER.debug("Could not parse %s from topic %s", label, topic)
            return

        if item_id not in discovered:
            _LOGGER.debug("Discovered %s %s (value: %s)", label, item_id, payload)
        discovered.add(item_id)
        activity["at"] = loop.time()

    if not await wait_for_mqtt_connected(coordinator):
        return discovered

    _LOGGER.debug("Subscribing to discovery topic: %s", discovery_topic)
    coordinator.subscribe(discovery_topic, discovery_handler)
    try:
        await _wait_for_discovery_idle(
            has_items=lambda: bool(discovered),
            last_activity=lambda: activity["at"],
        )
    finally:
        coordinator.unsubscribe(discovery_topic, discovery_handler)

    _LOGGER.info(
        "Discovery complete for %s: found %s",
        discovery_topic,
        sorted(discovered),
    )
    return discovered
