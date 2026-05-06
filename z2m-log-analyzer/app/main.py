import asyncio
import logging
import os
import signal
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.aggregator import Aggregator
from app.api.aggregates import router as aggregates_router
from app.api.devices import router as devices_router
from app.api.events import router as events_router
from app.api.settings import router as settings_router
from app.config import AppConfig, load_config
from app.mqtt_consumer import MQTTConsumer
from app.parser import parse_message
from app.publisher import Publisher
from app.storage import Database

logger = logging.getLogger(__name__)

Event = dict[str, Any]


async def _maybe_await(value: Any) -> Any:
    if isinstance(value, Awaitable):
        return await value
    return value


def _is_complete_event(event: Event) -> bool:
    return all(event.get(field) is not None for field in ("ts", "level", "category", "raw_message"))


def _normalise_event(event: Event) -> Event | None:
    if _is_complete_event(event):
        return event

    message = event.get("message") or event.get("raw_message")
    level = event.get("level")
    if not message or not level:
        return None

    parsed = parse_message(str(message), str(level))
    parsed.setdefault("ts", event.get("ts"))
    parsed.setdefault("raw_message", str(message))
    parsed.setdefault("level", str(level))
    if "meta" not in parsed and event.get("meta") is not None:
        parsed["meta"] = event["meta"]
    return parsed if _is_complete_event(parsed) else None


async def _event_writer(
    cfg: AppConfig,
    db: Database,
    publisher: Publisher | None,
    event_queue: asyncio.Queue[Event],
) -> None:
    while True:
        event = await event_queue.get()
        try:
            normalised = _normalise_event(event)
            if normalised is None:
                logger.warning("dropping incomplete event: %s", event)
                continue

            await db.insert_event(
                normalised["ts"],
                normalised["level"],
                normalised["category"],
                normalised.get("device"),
                normalised["raw_message"],
                normalised.get("meta"),
            )
            if cfg.enable_raw_events and publisher is not None:
                await publisher.publish_raw_event(normalised)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("failed to write event")
        finally:
            event_queue.task_done()


async def _retention_cleanup(cfg: AppConfig, db: Database, shutdown_event: asyncio.Event) -> None:
    while not shutdown_event.is_set():
        try:
            await db.cleanup_retention(cfg.retention_days)
            await db.check_db_size(cfg.db_max_size_mb)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("retention cleanup failed")

        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(shutdown_event.wait(), timeout=3600)


def _register_signal_handlers(shutdown_event: asyncio.Event) -> list[tuple[int, Callable[[], None]]]:
    loop = asyncio.get_running_loop()
    registered: list[tuple[int, Callable[[], None]]] = []

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            handler = shutdown_event.set
            loop.add_signal_handler(sig, handler)
            registered.append((sig, handler))
        except (NotImplementedError, RuntimeError, ValueError):
            logger.debug("signal handler not registered for %s", sig)

    return registered


def _remove_signal_handlers(registered: list[tuple[int, Callable[[], None]]]) -> None:
    loop = asyncio.get_running_loop()
    for sig, _ in registered:
        with suppress(NotImplementedError, RuntimeError, ValueError):
            loop.remove_signal_handler(sig)


async def _cancel_task(task: asyncio.Task[Any] | None, name: str) -> None:
    if task is None or task.done():
        return

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger.info("%s task cancelled", name)
    except Exception:
        logger.exception("%s task failed during cancellation", name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg: AppConfig | None = None
    db: Database | None = None
    mqtt: MQTTConsumer | None = None
    publisher: Publisher | None = None
    aggregator: Aggregator | None = None
    event_queue: asyncio.Queue[Event] | None = None
    mqtt_task: asyncio.Task[Any] | None = None
    event_writer_task: asyncio.Task[Any] | None = None
    retention_task: asyncio.Task[Any] | None = None
    shutdown_event = asyncio.Event()
    signal_handlers: list[tuple[int, Callable[[], None]]] = []

    try:
        try:
            active_cfg: AppConfig = load_config()
            cfg = active_cfg
            logging.basicConfig(level=active_cfg.log_level.upper())
            app.state.config = active_cfg
            app.state.shutdown_event = shutdown_event
            signal_handlers = _register_signal_handlers(shutdown_event)
        except Exception:
            logger.exception("startup failed while loading configuration")
            raise

        try:
            event_queue = asyncio.Queue(maxsize=10000)
            app.state.event_queue = event_queue
        except Exception:
            logger.exception("startup failed while creating event queue")
            raise

        try:
            active_db: Database = Database()
            db = active_db
            await active_db.__aenter__()
            app.state.db = active_db
        except Exception:
            logger.exception("startup failed while opening database")
            raise

        try:
            active_publisher: Publisher = Publisher(active_cfg, active_db)
            publisher = active_publisher
            app.state.publisher = active_publisher
            await active_publisher.start()
        except Exception:
            logger.exception("startup failed while starting publisher")
            raise

        async def on_aggregate_update(window: str, bucket_ts: int) -> None:
            if publisher is None:
                return
            await publisher.publish_state(window, bucket_ts)
            await publisher.publish_burst_state()

        try:
            active_mqtt: MQTTConsumer = MQTTConsumer(active_cfg, event_queue)
            mqtt = active_mqtt
            active_aggregator: Aggregator = Aggregator(active_cfg, active_db, on_aggregate_update)
            aggregator = active_aggregator
            app.state.mqtt = active_mqtt
            app.state.aggregator = active_aggregator
            active_publisher.set_aggregator(active_aggregator)
        except Exception:
            logger.exception("startup failed while creating components")
            raise

        try:
            event_writer_task = asyncio.create_task(
                _event_writer(active_cfg, active_db, active_publisher, event_queue),
                name="event-writer",
            )
            mqtt_task = asyncio.create_task(active_mqtt.start(), name="mqtt-consumer")
            await active_aggregator.start()
            retention_task = asyncio.create_task(
                _retention_cleanup(active_cfg, active_db, shutdown_event),
                name="retention-cleanup",
            )
            app.state.tasks = {
                "event_writer": event_writer_task,
                "mqtt": mqtt_task,
                "retention": retention_task,
            }
        except Exception:
            logger.exception("startup failed while creating background tasks")
            raise

        yield
    finally:
        shutdown_event.set()

        if mqtt is not None:
            try:
                await mqtt.stop()
            except Exception:
                logger.exception("failed to stop MQTT consumer")

        if event_queue is not None:
            try:
                await asyncio.wait_for(event_queue.join(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("event queue did not drain before shutdown timeout")
            except Exception:
                logger.exception("failed while draining event queue")

        if aggregator is not None:
            try:
                await aggregator.stop()
            except Exception:
                logger.exception("failed to stop aggregator")

        await _cancel_task(mqtt_task, "mqtt")
        await _cancel_task(retention_task, "retention")
        await _cancel_task(event_writer_task, "event writer")

        if publisher is not None:
            try:
                await publisher.stop()
            except Exception:
                logger.exception("failed to stop publisher")

        if db is not None:
            try:
                close = getattr(db, "close", None)
                if close is not None:
                    await _maybe_await(close())
                else:
                    await db.__aexit__(None, None, None)
            except Exception:
                logger.exception("failed to close database")

        _remove_signal_handlers(signal_handlers)


app = FastAPI(
    title="Zigbee2MQTT Log Analyzer",
    lifespan=lifespan,
    root_path=os.environ.get("INGRESS_PATH", ""),
)

app.include_router(events_router)
app.include_router(aggregates_router)
app.include_router(devices_router)
app.include_router(settings_router)

app.mount("/", StaticFiles(directory="app/ui", html=True), name="ui")
