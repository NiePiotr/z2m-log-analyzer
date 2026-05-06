import json
import logging

import aiomqtt

from app.config import AppConfig

logger = logging.getLogger(__name__)

DISCOVERY_PREFIX = "homeassistant/sensor/z2m_log_analyzer"
STATE_PREFIX = "zigbee2mqtt_log_analyzer/state"

_WINDOW_MS = {"1m": 60_000, "5m": 300_000, "1h": 3_600_000, "24h": 86_400_000}


class Publisher:
    def __init__(self, config: AppConfig, db):
        self._cfg = config
        self._db = db
        self._client: aiomqtt.Client | None = None
        self._aggregator: object | None = None

    def set_aggregator(self, aggregator):
        self._aggregator = aggregator

    async def start(self):
        try:
            self._client = aiomqtt.Client(
                hostname=self._cfg.mqtt_host,
                port=self._cfg.mqtt_port,
                username=self._cfg.mqtt_user,
                password=self._cfg.mqtt_password,
            )
            await self._client.__aenter__()
            await self._publish_discovery()
            logger.info("Publisher started")
        except Exception:
            logger.warning("MQTT unavailable — publisher disabled: %s:%d", self._cfg.mqtt_host, self._cfg.mqtt_port)
            if self._client:
                try:
                    await self._client.__aexit__(None, None, None)
                except Exception:
                    pass
            self._client = None

    async def stop(self):
        if self._client:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                pass
            self._client = None

    async def publish_state(self, window: str, bucket_ts: int):
        if not self._client:
            return
        for sensor_id in self._cfg.publish_sensors:
            parts = sensor_id.rsplit("_", 1)
            if len(parts) != 2 or parts[1] != window:
                continue
            sensor_level = parts[0]
            level_map = {"errors": "error", "warnings": "warning", "total": None}

            db_level = level_map.get(sensor_level, sensor_level)
            until_ts = bucket_ts + _WINDOW_MS.get(window, 60_000)
            rows = await self._db.get_aggregate_totals(
                window, bucket_ts, until_ts
            )
            if rows:
                count = sum(r["count"] for r in rows)
            else:
                count = 0

            topic = f"{STATE_PREFIX}/{sensor_id}"
            await self._client.publish(topic, str(count), retain=True)

    async def publish_raw_event(self, event: dict):
        if not self._cfg.enable_raw_events or not self._client:
            return
        payload = {
            "ts": event.get("ts"),
            "level": event.get("level"),
            "category": event.get("category"),
            "device": event.get("device"),
            "message": event.get("raw_message", ""),
        }
        await self._client.publish(
            self._cfg.raw_events_topic,
            json.dumps(payload),
        )

    async def publish_burst_state(self):
        if not self._client or not self._aggregator:
            return
        topic = f"{STATE_PREFIX}/burst_active"
        state = "ON" if getattr(self._aggregator, "_burst_active", False) else "OFF"
        await self._client.publish(topic, state, retain=True)

    async def _publish_discovery(self):
        if not self._client:
            return

        for sensor_id in self._cfg.publish_sensors:
            parts = sensor_id.rsplit("_", 1)
            if len(parts) != 2:
                continue
            sensor_name = sensor_id.replace("_", " ").title()

            config_topic = f"{DISCOVERY_PREFIX}/{sensor_id}/config"
            config_payload = {
                "name": f"Z2M {sensor_name}",
                "unique_id": f"z2m_log_analyzer_{sensor_id}",
                "state_topic": f"{STATE_PREFIX}/{sensor_id}",
                "unit_of_measurement": "events",
                "state_class": "total_increasing",
                "device": {
                    "identifiers": ["z2m_log_analyzer"],
                    "name": "Z2M Log Analyzer",
                    "manufacturer": "Community",
                    "model": "Z2M Log Analyzer",
                },
            }
            await self._client.publish(
                config_topic, json.dumps(config_payload), retain=True
            )
            logger.info("Published discovery config for %s", sensor_id)

        burst_config = {
            "name": "Z2M Burst Active",
            "unique_id": "z2m_log_analyzer_burst_active",
            "state_topic": f"{STATE_PREFIX}/burst_active",
            "device_class": "problem",
            "device": {
                "identifiers": ["z2m_log_analyzer"],
                "name": "Z2M Log Analyzer",
                "manufacturer": "Community",
                "model": "Z2M Log Analyzer",
            },
        }
        await self._client.publish(
            f"{DISCOVERY_PREFIX}/burst_active/config",
            json.dumps(burst_config),
            retain=True,
        )
        logger.info("Published burst detection binary sensor")
