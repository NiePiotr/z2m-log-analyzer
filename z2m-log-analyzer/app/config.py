"""Configuration loader for the Z2M Log Analyzer add-on.

Reads options from /data/options.json (injected by HA Supervisor) and
falls back to environment variables for standalone development.
"""

import json
import os
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

OPTIONS_PATH = "/data/options.json"


@dataclass
class AppConfig:
    base_topic: str = "zigbee2mqtt"
    retention_days: int = 30
    enable_raw_events: bool = False
    raw_events_topic: str = "zigbee2mqtt_log_analyzer/events"
    publish_sensors: list[str] = field(default_factory=lambda: [
        "errors_1h", "errors_24h", "warnings_1h", "warnings_24h",
        "failed_to_ping_1h",
    ])
    log_level: str = "info"
    db_max_size_mb: int = 500
    burst_window_minutes: int = 5
    burst_threshold: int = 10
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_user: Optional[str] = None
    mqtt_password: Optional[str] = None


def _load_options_file() -> dict:
    try:
        with open(OPTIONS_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.info("options.json not found — using defaults/env vars")
        return {}


def load_config() -> AppConfig:
    options = _load_options_file()

    cfg = AppConfig(
        base_topic=options.get("base_topic", "zigbee2mqtt"),
        retention_days=options.get("retention_days", 30),
        enable_raw_events=options.get("enable_raw_events", False),
        raw_events_topic=options.get("raw_events_topic", "zigbee2mqtt_log_analyzer/events"),
        publish_sensors=options.get("publish_sensors", [
            "errors_1h", "errors_24h", "warnings_1h", "warnings_24h",
            "failed_to_ping_1h",
        ]),
        log_level=options.get("log_level", "info"),
        db_max_size_mb=options.get("db_max_size_mb", 500),
        burst_window_minutes=options.get("burst_window_minutes", 5),
        burst_threshold=options.get("burst_threshold", 10),
        mqtt_host=os.environ.get("MQTTHOST") or options.get("mqtt_host", "localhost"),
        mqtt_port=int(os.environ.get("MQTTPORT") or options.get("mqtt_port", 1883)),
        mqtt_user=os.environ.get("MQTTUSER") or options.get("mqtt_user") or None,
        mqtt_password=os.environ.get("MQTTPASSWORD") or options.get("mqtt_password") or None,
    )

    logging.getLogger().setLevel(cfg.log_level.upper())
    return cfg
