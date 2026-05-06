import asyncio
import logging
import time

from app.config import AppConfig

logger = logging.getLogger(__name__)

WINDOWS = {
    "1m": 60_000,
    "5m": 300_000,
    "1h": 3_600_000,
    "24h": 86_400_000,
}


class Aggregator:
    def __init__(self, config: AppConfig, db, on_update=None):
        self._cfg = config
        self._db = db
        self._on_update = on_update
        self._shutdown = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._tick_count = 0
        self._burst_active = False
        self._burst_clear_at = 0

    async def start(self):
        self._shutdown.clear()
        await self._rebuild_if_needed()
        self._task = asyncio.create_task(self._tick_loop())

    async def stop(self):
        self._shutdown.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _rebuild_if_needed(self):
        last_ts_str = await self._db.get_meta("last_aggregated_ts")
        if last_ts_str is None:
            logger.info("No aggregation state found — rebuilding from events")
            await self._rebuild_all()
        else:
            logger.info("Resuming aggregation from ts=%s", last_ts_str)

    async def _rebuild_all(self):
        now_ms = int(time.time() * 1000)
        earliest_row = await self._db.fetch_all(
            "SELECT MIN(ts) AS min_ts FROM events", []
        )
        if not earliest_row or earliest_row[0]["min_ts"] is None:
            return
        start_ms = earliest_row[0]["min_ts"]

        for window_name, window_ms in WINDOWS.items():
            bucket_start = (start_ms // window_ms) * window_ms
            while bucket_start < now_ms:
                bucket_end = bucket_start + window_ms
                await self._aggregate_window(window_name, bucket_start, bucket_end)
                bucket_start = bucket_end

        await self._db.set_meta("last_aggregated_ts", str(now_ms))
        logger.info("Full rebuild complete")

    async def _aggregate_window(self, window_name: str, since_ms: int, until_ms: int):
        rows = await self._db.fetch_all(
            "SELECT level, category, device, COUNT(*) AS cnt "
            "FROM events WHERE ts >= ? AND ts < ? "
            "GROUP BY level, category, device",
            [since_ms, until_ms],
        )
        for row in rows:
            await self._db.upsert_aggregate(
                since_ms,
                window_name,
                row["level"],
                row["category"],
                row["device"],
                row["cnt"],
            )

    async def _tick_loop(self):
        while not self._shutdown.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Aggregator tick failed")

            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=60)
                break
            except asyncio.TimeoutError:
                pass

    async def _tick(self):
        self._tick_count += 1
        now_ms = int(time.time() * 1000)
        last_ts_str = await self._db.get_meta("last_aggregated_ts")
        since_ms = int(last_ts_str) if last_ts_str else now_ms - 120_000
        since_ms = max(since_ms, now_ms - 120_000)

        rows = await self._db.fetch_all(
            "SELECT level, category, device, COUNT(*) AS cnt "
            "FROM events WHERE ts >= ? AND ts < ? "
            "GROUP BY level, category, device",
            [since_ms, now_ms],
        )

        windows_to_update = {"1m"}
        if self._tick_count % 5 == 0:
            windows_to_update.add("5m")
        if self._tick_count % 60 == 0:
            windows_to_update.add("1h")
        if self._tick_count % 1440 == 0:
            windows_to_update.add("24h")

        for window_name in windows_to_update:
            window_ms = WINDOWS[window_name]
            bucket_ts = (now_ms // window_ms) * window_ms

            if window_name == "1m":
                for row in rows:
                    await self._db.upsert_aggregate(
                        bucket_ts, window_name, row["level"],
                        row["category"], row["device"], row["cnt"],
                    )
            else:
                sub_since = bucket_ts
                sub_until = bucket_ts + window_ms
                agg_rows = await self._db.fetch_all(
                    "SELECT level, category, device, SUM(count) AS cnt "
                    "FROM aggregates WHERE window = '1m' "
                    "AND bucket_ts >= ? AND bucket_ts < ? "
                    "GROUP BY level, category, device",
                    [sub_since, sub_until],
                )
                for row in agg_rows:
                    await self._db.upsert_aggregate(
                        bucket_ts, window_name, row["level"],
                        row["category"], row["device"], row["cnt"],
                    )

            if self._on_update:
                try:
                    await self._on_update(window_name, bucket_ts)
                except Exception:
                    logger.exception("on_update callback failed")

            if window_name == "1m":
                self._check_burst(bucket_ts)

        await self._db.set_meta("last_aggregated_ts", str(now_ms))

    async def _check_burst(self, bucket_ts: int):
        window_ms = self._cfg.burst_window_minutes * 60_000
        since = bucket_ts - window_ms
        totals = await self._db.get_aggregate_totals("1m", since, bucket_ts + 60_000)
        total = sum(r["count"] for r in totals) if totals else 0
        if total >= self._cfg.burst_threshold and not self._burst_active:
            self._burst_active = True
            self._burst_clear_at = bucket_ts + window_ms
            logger.warning("Burst detected: %d events in %d minutes", total, self._cfg.burst_window_minutes)
        elif self._burst_active and bucket_ts >= self._burst_clear_at:
            self._burst_active = False
            logger.info("Burst cleared")
