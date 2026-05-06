import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

import aiosqlite
import orjson


logger = logging.getLogger(__name__)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    level TEXT NOT NULL,
    category TEXT NOT NULL,
    device TEXT,
    raw_message TEXT NOT NULL,
    meta TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_device_ts ON events(device, ts);
CREATE INDEX IF NOT EXISTS idx_events_category_ts ON events(category, ts);
CREATE INDEX IF NOT EXISTS idx_events_level_ts ON events(level, ts);

CREATE TABLE IF NOT EXISTS aggregates (
    bucket_ts INTEGER NOT NULL,
    window TEXT NOT NULL,
    level TEXT NOT NULL,
    category TEXT NOT NULL,
    device TEXT,
    count INTEGER NOT NULL,
    PRIMARY KEY (bucket_ts, window, level, category, device)
);

CREATE TABLE IF NOT EXISTS meta_kv (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


_CURRENT_VERSION = 1
_migrations = {
    1: [_SCHEMA_SQL],
}


class Database:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or os.environ.get("Z2M_DB_PATH", "./z2m_log_analyzer.db")
        self._write_conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()
        self._read_connections: set[aiosqlite.Connection] = set()
        self._closed = False

    async def __aenter__(self) -> "Database":
        await self.init()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def init(self) -> None:
        try:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self._write_conn = await aiosqlite.connect(self.path)
            self._write_conn.row_factory = aiosqlite.Row
            await self._write_conn.execute("PRAGMA journal_mode=WAL")
            await self._write_conn.execute("PRAGMA foreign_keys=ON")
            await self._apply_migrations()
            await self._write_conn.commit()
        except Exception:
            logger.exception("Failed to initialize database")
            raise

    async def insert_event(
        self,
        ts: int,
        level: str,
        category: str,
        device: str | None,
        raw_message: str,
        meta: Any = None,
    ) -> int | None:
        try:
            meta_json = self._dump_meta(meta)
            async with self._write_lock:
                conn = self._require_write_conn()
                cursor = await conn.execute(
                    """
                    INSERT INTO events (ts, level, category, device, raw_message, meta)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (ts, level, category, device, raw_message, meta_json),
                )
                await conn.commit()
                return cursor.lastrowid
        except Exception:
            logger.exception("Failed to insert event")
            return None

    async def get_events(
        self,
        since_ts: int | None = None,
        until_ts: int | None = None,
        level: str | None = None,
        category: str | None = None,
        device: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        try:
            where, params = self._build_filters(since_ts, until_ts, level, category, device)
            params.extend((limit, offset))
            query = f"""
                SELECT id, ts, level, category, device, raw_message, meta
                FROM events
                {where}
                ORDER BY ts DESC, id DESC
                LIMIT ? OFFSET ?
            """
            return await self.fetch_all(query, params)
        except Exception:
            logger.exception("Failed to get events")
            return []

    async def get_event_count(
        self,
        since_ts: int | None = None,
        until_ts: int | None = None,
        level: str | None = None,
        category: str | None = None,
        device: str | None = None,
    ) -> int:
        try:
            where, params = self._build_filters(since_ts, until_ts, level, category, device)
            rows = await self.fetch_all(f"SELECT COUNT(*) AS count FROM events {where}", params)
            return int(rows[0]["count"]) if rows else 0
        except Exception:
            logger.exception("Failed to get event count")
            return 0

    async def upsert_aggregate(
        self,
        bucket_ts: int,
        window: str,
        level: str,
        category: str,
        device: str | None,
        count: int,
    ) -> None:
        try:
            async with self._write_lock:
                conn = self._require_write_conn()
                await conn.execute(
                    """
                    INSERT INTO aggregates (bucket_ts, window, level, category, device, count)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(bucket_ts, window, level, category, device)
                    DO UPDATE SET count = count + excluded.count
                    """,
                    (bucket_ts, window, level, category, device, count),
                )
                await conn.commit()
        except Exception:
            logger.exception("Failed to upsert aggregate")

    async def get_aggregates(
        self,
        window: str,
        since_ts: int,
        until_ts: int,
        level: str | None = None,
        category: str | None = None,
        device: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            where = ["window = ?", "bucket_ts >= ?", "bucket_ts <= ?"]
            params: list[Any] = [window, since_ts, until_ts]
            self._append_optional_filters(where, params, level, category, device)
            query = f"""
                SELECT bucket_ts, window, level, category, device, count
                FROM aggregates
                WHERE {' AND '.join(where)}
                ORDER BY bucket_ts ASC
            """
            return await self.fetch_all(query, params)
        except Exception:
            logger.exception("Failed to get aggregates")
            return []

    async def get_aggregate_totals(
        self,
        window: str,
        since_ts: int,
        until_ts: int,
        device: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            where = ["window = ?", "bucket_ts >= ?", "bucket_ts <= ?"]
            params: list[Any] = [window, since_ts, until_ts]
            if device is not None:
                where.append("device = ?")
                params.append(device)
            query = f"""
                SELECT category, SUM(count) AS count
                FROM aggregates
                WHERE {' AND '.join(where)}
                GROUP BY category
                ORDER BY count DESC, category ASC
            """
            return await self.fetch_all(query, params)
        except Exception:
            logger.exception("Failed to get aggregate totals")
            return []

    async def get_device_ranking(self, since_ts: int, until_ts: int, limit: int = 20) -> list[dict[str, Any]]:
        try:
            query = """
                SELECT device, COUNT(*) AS total
                FROM events
                WHERE ts >= ? AND ts <= ? AND device IS NOT NULL AND device != ''
                GROUP BY device
                ORDER BY total DESC, device ASC
                LIMIT ?
            """
            rows = await self.fetch_all(query, [since_ts, until_ts, limit])
            results = []
            for row in rows:
                dev = row["device"]
                cat_rows = await self.fetch_all(
                    "SELECT category, COUNT(*) AS cnt FROM events "
                    "WHERE device = ? AND ts >= ? AND ts <= ? "
                    "GROUP BY category ORDER BY cnt DESC",
                    [dev, since_ts, until_ts],
                )
                results.append({
                    "device": dev,
                    "total": row["total"],
                    "categories": {r["category"]: r["cnt"] for r in cat_rows},
                })
            return results
        except Exception:
            logger.exception("Failed to get device ranking")
            return []

    async def get_device_detail(self, device: str, since_ts: int, until_ts: int) -> dict[str, Any]:
        try:
            rows = await self.fetch_all(
                "SELECT ts, level, category, raw_message FROM events "
                "WHERE device = ? AND ts >= ? AND ts <= ? "
                "ORDER BY ts DESC LIMIT 100",
                [device, since_ts, until_ts],
            )
            sparkline = await self.fetch_all(
                "SELECT bucket_ts, SUM(count) AS cnt FROM aggregates "
                "WHERE device = ? AND window = '1h' AND bucket_ts >= ? AND bucket_ts <= ? "
                "GROUP BY bucket_ts ORDER BY bucket_ts",
                [device, since_ts, until_ts],
            )
            cats = await self.fetch_all(
                "SELECT category, COUNT(*) AS cnt FROM events "
                "WHERE device = ? AND ts >= ? AND ts <= ? "
                "GROUP BY category ORDER BY cnt DESC",
                [device, since_ts, until_ts],
            )
            levels = await self.fetch_all(
                "SELECT level, COUNT(*) AS cnt FROM events "
                "WHERE device = ? AND ts >= ? AND ts <= ? "
                "GROUP BY level ORDER BY cnt DESC",
                [device, since_ts, until_ts],
            )
            last_row = await self.fetch_all(
                "SELECT MAX(ts) AS last_ts FROM events WHERE device = ?",
                [device],
            )
            total = sum(r["cnt"] for r in cats)
            return {
                "device": device,
                "total": total,
                "categories": {r["category"]: r["cnt"] for r in cats},
                "levels": {r["level"]: r["cnt"] for r in levels},
                "sparkline": [{"ts": r["bucket_ts"], "count": r["cnt"]} for r in sparkline],
                "recent_events": [dict(r) for r in rows],
                "last_seen": last_row[0]["last_ts"] if last_row and last_row[0]["last_ts"] else None,
            }
        except Exception:
            logger.exception("Failed to get device detail for %s", device)
            return {}

    async def get_categories_summary(self, since_ts: int, until_ts: int) -> list[dict[str, Any]]:
        try:
            query = """
                SELECT category, COUNT(*) AS total
                FROM events
                WHERE ts >= ? AND ts <= ?
                GROUP BY category
                ORDER BY total DESC, category ASC
            """
            return await self.fetch_all(query, [since_ts, until_ts])
        except Exception:
            logger.exception("Failed to get categories summary")
            return []

    async def cleanup_retention(self, retention_days: int) -> None:
        try:
            now_ms = int(time.time() * 1000)
            event_cutoff = now_ms - retention_days * 86_400_000
            aggregate_cutoff = now_ms - 7 * 86_400_000
            async with self._write_lock:
                conn = self._require_write_conn()
                await conn.execute("DELETE FROM events WHERE ts < ?", (event_cutoff,))
                await conn.execute(
                    "DELETE FROM aggregates WHERE window IN (?, ?) AND bucket_ts < ?",
                    ("1m", "5m", aggregate_cutoff),
                )
                await conn.commit()
        except Exception:
            logger.exception("Failed to cleanup retained data")

    async def check_db_size(self, max_size_mb: int) -> bool:
        try:
            db_file = Path(self.path)
            if not db_file.exists():
                return False
            return db_file.stat().st_size > max_size_mb * 1024 * 1024
        except Exception:
            logger.exception("Failed to check database size")
            return False

    async def get_db_size_mb(self) -> float:
        try:
            db_file = Path(self.path)
            if not db_file.exists():
                return 0.0
            return db_file.stat().st_size / (1024 * 1024)
        except Exception:
            return 0.0

    async def get_meta(self, key: str) -> str | None:
        try:
            cursor = await self._write_conn.execute(
                "SELECT value FROM meta_kv WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
            return row[0] if row else None
        except Exception:
            return None

    async def set_meta(self, key: str, value: str) -> None:
        try:
            async with self._write_lock:
                await self._write_conn.execute(
                    "INSERT OR REPLACE INTO meta_kv (key, value) VALUES (?, ?)",
                    (key, value),
                )
                await self._write_conn.commit()
        except Exception:
            logger.exception("Failed to set meta key %s", key)

    async def vacuum(self) -> None:
        try:
            async with self._write_lock:
                conn = self._require_write_conn()
                await conn.execute("VACUUM")
                await conn.commit()
        except Exception:
            logger.exception("Failed to vacuum database")

    async def close(self) -> None:
        if self._closed:
            return
        try:
            if self._write_conn is not None:
                await self._write_conn.close()
                self._write_conn = None
            for conn in list(self._read_connections):
                await conn.close()
            self._read_connections.clear()
            self._closed = True
        except Exception:
            logger.exception("Failed to close database")

    async def _apply_migrations(self) -> None:
        conn = self._require_write_conn()
        await conn.executescript(_SCHEMA_SQL)
        cursor = await conn.execute(
            "SELECT value FROM meta_kv WHERE key = ?", ("schema_version",)
        )
        row = await cursor.fetchone()
        current_version = int(row[0]) if row and row[0] else 0
        for version in range(current_version + 1, _CURRENT_VERSION + 1):
            scripts = _migrations.get(version, [])
            for script in scripts:
                await conn.executescript(script)
            logger.info("Applied migration v%d", version)
        await conn.execute(
            "INSERT OR REPLACE INTO meta_kv (key, value) VALUES (?, ?)",
            ("schema_version", str(_CURRENT_VERSION)),
        )

    async def fetch_all(self, query: str, params: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
        conn = await self._open_read_conn()
        try:
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]
        finally:
            await conn.close()
            self._read_connections.discard(conn)

    async def _open_read_conn(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        self._read_connections.add(conn)
        return conn

    def _require_write_conn(self) -> aiosqlite.Connection:
        if self._write_conn is None:
            raise RuntimeError("Database is not initialized")
        return self._write_conn

    def _build_filters(
        self,
        since_ts: int | None,
        until_ts: int | None,
        level: str | None,
        category: str | None,
        device: str | None,
    ) -> tuple[str, list[Any]]:
        where: list[str] = []
        params: list[Any] = []
        if since_ts is not None:
            where.append("ts >= ?")
            params.append(since_ts)
        if until_ts is not None:
            where.append("ts <= ?")
            params.append(until_ts)
        self._append_optional_filters(where, params, level, category, device)
        return (f"WHERE {' AND '.join(where)}" if where else "", params)

    def _append_optional_filters(
        self,
        where: list[str],
        params: list[Any],
        level: str | None,
        category: str | None,
        device: str | None,
    ) -> None:
        if level is not None:
            where.append("level = ?")
            params.append(level)
        if category is not None:
            where.append("category = ?")
            params.append(category)
        if device is not None:
            where.append("device = ?")
            params.append(device)

    def _row_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        item = dict(row)
        if "meta" in item and item["meta"] is not None:
            try:
                item["meta"] = orjson.loads(item["meta"])
            except orjson.JSONDecodeError:
                logger.exception("Failed to decode event metadata")
        return item

    def _dump_meta(self, meta: Any) -> str | None:
        if meta is None:
            return None
        if isinstance(meta, str):
            return meta
        return orjson.dumps(meta).decode("utf-8")
