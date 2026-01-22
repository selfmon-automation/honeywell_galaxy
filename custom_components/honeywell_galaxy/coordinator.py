"""DataUpdateCoordinator for Honeywell Galaxy."""
from __future__ import annotations

import logging
from typing import Any, Callable

import paho.mqtt.client as mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _topic_matches(topic: str, pattern: str) -> bool:
    """Check if a topic matches a pattern (supports + and # wildcards)."""
    if pattern == topic:
        return True
    
    # Convert pattern to regex
    import re
    pattern_re = pattern.replace("+", "[^/]+").replace("#", ".*")
    pattern_re = f"^{pattern_re}$"
    return bool(re.match(pattern_re, topic))


class GalaxyCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from MQTT."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
        )
        self.entry = entry
        self.client: mqtt.Client | None = None
        self.connected = False
        self.subscriptions: dict[str, list[Callable[[str, str], None]]] = {}

    async def async_config_entry_first_refresh(self) -> None:
        """Connect to MQTT on first refresh."""
        await self._connect_mqtt()

    async def _connect_mqtt(self) -> None:
        """Connect to MQTT broker."""
        config = self.entry.data
        host = config["host"]
        port = config.get("port", 1883)
        protocol = config.get("protocol", "mqtt")
        username = config.get("username") or config.get(CONF_USERNAME)
        password = config.get("password") or config.get(CONF_PASSWORD)

        client_id = f"homeassistant-{DOMAIN}-{self.entry.entry_id}"

        try:
            self.client = mqtt.Client(client_id=client_id)

            # Set username/password if provided (even if empty string)
            # Some brokers require authentication even with empty credentials
            if username is not None or password is not None:
                # Handle None values - convert to empty string if needed
                username_str = username if username is not None else ""
                password_str = password if password is not None else ""
                self.client.username_pw_set(username_str, password_str)
                _LOGGER.debug(f"Setting MQTT credentials: username='{username_str}' (password {'set' if password_str else 'not set'})")
            else:
                _LOGGER.debug("No MQTT credentials provided, connecting without authentication")
        except Exception as e:
            _LOGGER.error(f"Failed to create MQTT client: {e}")
            return

        def on_connect(client, userdata, flags, rc):
            """Handle connection."""
            if rc == 0:
                self.connected = True
                _LOGGER.info(f"Connected to MQTT broker at {host}:{port}")
                # Subscribe to all queued topics
                # Make a copy of keys to avoid RuntimeError if subscriptions are modified during iteration
                if self.subscriptions:
                    topics_to_subscribe = list(self.subscriptions.keys())
                    _LOGGER.info(f"Subscribing to {len(topics_to_subscribe)} topic(s) on connect")
                    for topic in topics_to_subscribe:
                        result = client.subscribe(topic, qos=0)
                        if result[0] == mqtt.MQTT_ERR_SUCCESS:
                            _LOGGER.info(f"Successfully subscribed to {topic} (QoS: {result[1]})")
                        else:
                            _LOGGER.error(f"Failed to subscribe to {topic}: {result[0]} - {mqtt.error_string(result[0])}")
                else:
                    _LOGGER.info("No topics to subscribe to on connect")
            elif rc == 5:
                self.connected = False
                _LOGGER.error(f"MQTT authentication failed (not authorised). Check username/password. RC: {rc}")
                _LOGGER.error(f"Attempted connection with username: '{username if username else '(none)'}'")
            else:
                self.connected = False
                _LOGGER.error(f"Failed to connect to MQTT broker: {rc} - {mqtt.error_string(rc)}")

        def on_disconnect(client, userdata, rc):
            """Handle disconnection."""
            self.connected = False
            _LOGGER.warning("Disconnected from MQTT broker")

        def on_message(client, userdata, msg):
            """Handle incoming message."""
            topic = msg.topic
            try:
                payload = msg.payload.decode("utf-8")
            except UnicodeDecodeError:
                _LOGGER.warning(f"Failed to decode payload for {topic}, using raw bytes")
                payload = str(msg.payload)
            
            # Check for exact topic match first
            if topic in self.subscriptions:
                _LOGGER.info(f"Received MQTT message on subscribed topic {topic}: {payload}")
                _LOGGER.debug(f"Found {len(self.subscriptions[topic])} callback(s) for topic {topic}")
                for callback in self.subscriptions[topic]:
                    try:
                        callback(topic, payload)
                        _LOGGER.debug(f"Successfully called callback for {topic}")
                    except Exception as e:
                        _LOGGER.error(f"Error in callback for {topic}: {e}", exc_info=True)
            else:
                # Check for wildcard topic matches
                matched = False
                for sub_topic, callbacks in self.subscriptions.items():
                    if _topic_matches(topic, sub_topic):
                        matched = True
                        _LOGGER.info(f"Received MQTT message on wildcard topic {sub_topic} (matched: {topic}): {payload}")
                        for callback in callbacks:
                            try:
                                callback(topic, payload)
                                _LOGGER.debug(f"Successfully called callback for wildcard {sub_topic}")
                            except Exception as e:
                                _LOGGER.error(f"Error in callback for wildcard {sub_topic}: {e}", exc_info=True)
                        break
                
                if not matched:
                    # Log unmatched topics for debugging (at debug level to avoid spam)
                    _LOGGER.debug(f"Received message on unsubscribed topic: {topic} (subscribed topics: {list(self.subscriptions.keys())})")

        self.client.on_connect = on_connect
        self.client.on_disconnect = on_disconnect
        self.client.on_message = on_message

        if protocol in ["mqtts", "wss"]:
            import ssl
            self.client.tls_set(cert_reqs=ssl.CERT_NONE)

        try:
            if protocol in ["ws", "wss"]:
                _LOGGER.warning("WebSocket transport not fully supported, using TCP")
            
            _LOGGER.info(f"Attempting to connect to MQTT broker at {host}:{port} (protocol: {protocol})")
            result = self.client.connect(host, port, keepalive=60)
            if result == mqtt.MQTT_ERR_SUCCESS:
                self.client.loop_start()
                _LOGGER.info("MQTT client loop started, waiting for connection...")
            else:
                _LOGGER.error(f"Failed to initiate MQTT connection: {result} - {mqtt.error_string(result)}")
                self.connected = False
        except Exception as e:
            _LOGGER.error(f"Exception connecting to MQTT broker: {e}", exc_info=True)
            self.connected = False

    def subscribe(self, topic: str, callback: Callable[[str, str], None]) -> None:
        """Subscribe to an MQTT topic."""
        if topic not in self.subscriptions:
            self.subscriptions[topic] = []
        self.subscriptions[topic].append(callback)
        _LOGGER.info(f"Registered subscription callback for {topic} (total callbacks: {len(self.subscriptions[topic])})")

        # Always try to subscribe if client exists, even if not yet connected
        # The subscription will be retried on connect
        if self.client:
            if self.connected:
                result = self.client.subscribe(topic, qos=0)
                if result[0] == mqtt.MQTT_ERR_SUCCESS:
                    _LOGGER.info(f"Subscribed to {topic} (QoS: {result[1]})")
                else:
                    _LOGGER.error(f"Failed to subscribe to {topic}: {result[0]} - {mqtt.error_string(result[0])}")
            else:
                _LOGGER.info(f"Subscription queued for {topic} (will subscribe when MQTT connects)")
        else:
            _LOGGER.info(f"Subscription queued for {topic} (MQTT client not yet created)")

    def unsubscribe(self, topic: str, callback: Callable[[str, str], None]) -> None:
        """Unsubscribe from an MQTT topic."""
        if topic in self.subscriptions:
            if callback in self.subscriptions[topic]:
                self.subscriptions[topic].remove(callback)
            if not self.subscriptions[topic]:
                del self.subscriptions[topic]
                if self.client and self.connected:
                    self.client.unsubscribe(topic)
                    _LOGGER.debug(f"Unsubscribed from {topic}")

    def publish(self, topic: str, payload: str) -> None:
        """Publish to an MQTT topic."""
        if not self.client:
            _LOGGER.error(f"Cannot publish to {topic}: MQTT client not initialized")
            return
        
        if not self.connected:
            _LOGGER.error(f"Cannot publish to {topic}: MQTT not connected")
            return
        
        try:
            result = self.client.publish(topic, payload, qos=0, retain=False)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                _LOGGER.info(f"Published to {topic}: {payload}")
            else:
                _LOGGER.error(f"Failed to publish to {topic}: {result.rc} - {mqtt.error_string(result.rc)}")
        except Exception as e:
            _LOGGER.error(f"Exception publishing to {topic}: {e}")

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None
        self.connected = False
