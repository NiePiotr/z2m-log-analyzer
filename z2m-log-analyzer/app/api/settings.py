import json
import logging
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

OPTIONS_PATH = "/data/options.json"


class SettingsUpdate(BaseModel):
    retention_days: int | None = None
    enable_raw_events: bool | None = None
    raw_events_topic: str | None = None
    publish_sensors: list[str] | None = None
    log_level: str | None = None


@router.get("")
async def get_settings(request: Request):
    cfg = request.app.state.config
    db = request.app.state.db

    db_size_mb = await db.get_db_size_mb()
    db_over_limit = await db.check_db_size(cfg.db_max_size_mb)

    mqtt_connected = False
    if hasattr(request.app.state, "mqtt") and request.app.state.mqtt:
        mqtt_connected = request.app.state.mqtt.connected

    return {
        "base_topic": cfg.base_topic,
        "retention_days": cfg.retention_days,
        "enable_raw_events": cfg.enable_raw_events,
        "raw_events_topic": cfg.raw_events_topic,
        "publish_sensors": cfg.publish_sensors,
        "log_level": cfg.log_level,
        "db_max_size_mb": cfg.db_max_size_mb,
        "db_size_mb": round(db_size_mb, 2),
        "db_over_limit": db_over_limit,
        "mqtt_connected": mqtt_connected,
    }


@router.post("")
async def update_settings(request: Request, body: SettingsUpdate):
    try:
        with open(OPTIONS_PATH, "r") as f:
            options = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        options = {}

    updates = body.model_dump(exclude_none=True)
    options.update(updates)

    try:
        with open(OPTIONS_PATH, "w") as f:
            json.dump(options, f, indent=2)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Cannot write config: {e}")

    cfg = request.app.state.config
    for key, value in updates.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)

    logger.info("Settings updated: %s", list(updates.keys()))
    return {"status": "ok", "updated": list(updates.keys())}


@router.get("/health")
async def health_check(request: Request):
    db = request.app.state.db
    cfg = request.app.state.config

    db_size_mb = await db.get_db_size_mb()
    db_over_limit = await db.check_db_size(cfg.db_max_size_mb)

    mqtt_connected = False
    if hasattr(request.app.state, "mqtt") and request.app.state.mqtt:
        mqtt_connected = request.app.state.mqtt.connected

    return {
        "status": "ok",
        "db_size_mb": round(db_size_mb, 2),
        "db_over_limit": db_over_limit,
        "mqtt_connected": mqtt_connected,
    }
