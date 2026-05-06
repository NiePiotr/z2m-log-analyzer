import asyncio
import json
import logging
import random
import time
from contextlib import suppress
from typing import Any

import aiomqtt

from app.config import AppConfig
from app.parser import parse_message

logger = logging.getLogger(__name__)


class MQTTConsumer:
    def __init__(self, config: AppConfig, event_queue: asyncio.Queue) -> None:
        self.config = config
        self.event_queue = event_queue
        self.device_map: dict[str, str] = {}
        self._client_id = f"z2m_log_analyzer_{random.randrange(0x100000):05x}"
        self._stop_event = asyncio.Event()
        self._client: aiomqtt.Client | None = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        self._stop_event.clear()
        backoff_seconds = 1

        while not self._stop_event.is_set():
            try:
                async with self._create_client() as client:
                    self._client = client
                    self._connected = True
                    logger.info("Connected to MQTT broker at %s:%s", self.config.mqtt_host, self.config.mqtt_port)
                    await self._fetch_device_map()
                    await client.subscribe(self._logging_topic)
                    logger.info("Subscribed to MQTT topic %s", self._logging_topic)
                    backoff_seconds = 1
                    await self._consume_messages(client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                logger.warning("MQTT connection lost: %s; reconnecting in %ss", exc, backoff_seconds)
                await self._wait_before_reconnect(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 60)
            finally:
                self._client = None
                self._connected = False

        logger.info("MQTT consumer stopped")

    async def stop(self) -> None:
        self._stop_event.set()
        client = self._client
        if client is not None:
            with suppress(Exception):
                await client.unsubscribe(self._logging_topic)
            with suppress(Exception):
                await client.__aexit__(None, None, None)

    async def _fetch_device_map(self) -> None:
        client = self._client
        if client is None:
            return

        await client.subscribe(self._devices_topic)
        try:
            async with asyncio.timeout(5):
                async for message in client.messages:
                    if self._stop_event.is_set():
                        return
                    if str(message.topic) != self._devices_topic:
                        continue
                    self._update_device_map(message.payload)
                    logger.info("Loaded %s devices from %s", len(self.device_map), self._devices_topic)
                    return
        except TimeoutError:
            logger.warning("Timed out waiting for %s", self._devices_topic)
        finally:
            with suppress(Exception):
                await client.unsubscribe(self._devices_topic)

    async def _consume_messages(self, client: aiomqtt.Client) -> None:
        async for message in client.messages:
            if self._stop_event.is_set():
                return
            if str(message.topic) != self._logging_topic:
                continue
            await self._process_logging_payload(message.payload)

    async def _process_logging_payload(self, payload: bytes | bytearray | memoryview | str) -> None:
        try:
            data = json.loads(self._decode_payload(payload))
        except json.JSONDecodeError as exc:
            logger.warning("Skipping invalid JSON MQTT payload: %s", exc)
            return

        message = data.get("message")
        level = data.get("level")
        if not isinstance(message, str) or not isinstance(level, str):
            logger.warning("Skipping MQTT payload without string level/message: %r", data)
            return

        event = parse_message(message, level)
        event["ts"] = int(time.time() * 1000)
        if "meta" in data:
            event["meta"] = data["meta"]

        await self.event_queue.put(event)
        logger.debug("Processed MQTT log event: %s", event)

    def _update_device_map(self, payload: bytes | bytearray | memoryview | str) -> None:
        try:
            data = json.loads(self._decode_payload(payload))
        except json.JSONDecodeError as exc:
            logger.warning("Skipping invalid JSON device payload: %s", exc)
            return

        if not isinstance(data, list):
            logger.warning("Skipping unexpected device payload: %r", data)
            return

        device_map: dict[str, str] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            friendly_name = item.get("friendly_name")
            ieee_address = item.get("ieee_address")
            if isinstance(friendly_name, str) and isinstance(ieee_address, str):
                device_map[friendly_name] = ieee_address

        self.device_map = device_map

    def _create_client(self) -> aiomqtt.Client:
        return aiomqtt.Client(
            hostname=self.config.mqtt_host,
            port=self.config.mqtt_port,
            username=self.config.mqtt_user,
            password=self.config.mqtt_password,
            identifier=self._client_id,
        )

    async def _wait_before_reconnect(self, delay_seconds: int) -> None:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay_seconds)
        except TimeoutError:
            return

    @staticmethod
    def _decode_payload(payload: bytes | bytearray | memoryview | str) -> str:
        if isinstance(payload, str):
            return payload
        return bytes(payload).decode("utf-8")

    @property
    def _logging_topic(self) -> str:
        return f"{self.config.base_topic}/bridge/logging"

    @property
    def _devices_topic(self) -> str:
        return f"{self.config.base_topic}/bridge/devices"
