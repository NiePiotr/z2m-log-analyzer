import json
import os
import tempfile
import time

import pytest
import pytest_asyncio

os.environ["Z2M_DB_PATH"] = ":memory:"

pytestmark = pytest.mark.asyncio

from app.storage import Database


@pytest_asyncio.fixture
async def db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = tmp.name
    tmp.close()
    try:
        async with Database(path) as database:
            yield database
    finally:
        os.unlink(path)


class TestDatabase:
    async def test_insert_and_get_event(self, db):
        ts = int(time.time() * 1000)
        row_id = await db.insert_event(ts, "error", "failed_to_ping", "kitchen_motion", "Failed to ping 'kitchen_motion'")
        assert row_id is not None

        events = await db.get_events(since_ts=ts - 1000, limit=10)
        assert len(events) > 0
        assert events[0]["category"] == "failed_to_ping"
        assert events[0]["device"] == "kitchen_motion"
        assert events[0]["level"] == "error"

    async def test_get_event_count(self, db):
        ts = int(time.time() * 1000)
        await db.insert_event(ts, "warning", "device_announce", "dev1", "msg1")
        await db.insert_event(ts + 1, "error", "failed_to_ping", "dev2", "msg2")

        total = await db.get_event_count(since_ts=ts)
        assert total == 2

        errors = await db.get_event_count(since_ts=ts, level="error")
        assert errors == 1

    async def test_filter_events(self, db):
        ts = int(time.time() * 1000)
        await db.insert_event(ts, "error", "failed_to_ping", "dev_a", "msg")
        await db.insert_event(ts + 1, "warning", "device_announce", "dev_b", "msg")

        filtered = await db.get_events(level="error")
        assert len(filtered) >= 1
        for e in filtered:
            assert e["level"] == "error"

    async def test_upsert_aggregate(self, db):
        ts = int(time.time() * 1000)
        bucket = (ts // 60000) * 60000

        await db.upsert_aggregate(bucket, "1m", "error", "failed_to_ping", "dev1", 5)
        await db.upsert_aggregate(bucket, "1m", "error", "failed_to_ping", "dev1", 3)

        rows = await db.get_aggregates("1m", bucket, bucket + 60000, level="error")
        assert len(rows) == 1
        assert rows[0]["count"] == 8

    async def test_get_aggregate_totals(self, db):
        ts = int(time.time() * 1000)
        bucket = (ts // 60000) * 60000

        await db.upsert_aggregate(bucket, "1m", "error", "failed_to_ping", "dev1", 5)
        await db.upsert_aggregate(bucket, "1m", "error", "publish_failed", "dev2", 2)

        totals = await db.get_aggregate_totals("1m", bucket, bucket + 60000)
        assert len(totals) == 2
        cats = {r["category"]: r["count"] for r in totals}
        assert cats.get("failed_to_ping", 0) >= 5
        assert cats.get("publish_failed", 0) >= 2

    async def test_device_ranking(self, db):
        ts = int(time.time() * 1000)
        await db.insert_event(ts, "error", "failed_to_ping", "device_x", "msg1")
        await db.insert_event(ts, "error", "failed_to_ping", "device_x", "msg2")
        await db.insert_event(ts, "warning", "publish_failed", "device_y", "msg3")

        ranking = await db.get_device_ranking(ts - 1000, ts + 1000)
        assert len(ranking) >= 2
        top = ranking[0]
        assert top["device"] == "device_x"
        assert top["total"] == 2

    async def test_categories_summary(self, db):
        ts = int(time.time() * 1000)
        await db.insert_event(ts, "error", "failed_to_ping", "d1", "msg1")
        await db.insert_event(ts, "error", "failed_to_ping", "d2", "msg2")
        await db.insert_event(ts, "warning", "publish_failed", "d3", "msg3")

        summary = await db.get_categories_summary(ts - 1000, ts + 1000)
        cats = {r["category"]: r["total"] for r in summary}
        assert cats["failed_to_ping"] >= 2
        assert cats["publish_failed"] >= 1

    async def test_retention_cleanup(self, db):
        ts = int(time.time() * 1000)
        old_ts = ts - 31 * 86_400_000
        recent_ts = ts - 1 * 86_400_000

        await db.insert_event(old_ts, "info", "device_announce", "old_dev", "old")
        await db.insert_event(recent_ts, "error", "failed_to_ping", "recent_dev", "recent")

        await db.cleanup_retention(30)

        events = await db.get_events(limit=100)
        devices = {e["device"] for e in events}
        assert "old_dev" not in devices

    async def test_db_size_check(self, db):
        over_limit = await db.check_db_size(500)
        assert not over_limit

    async def test_get_aggregates_ordering(self, db):
        ts = int(time.time() * 1000)
        b1 = (ts // 60000) * 60000
        b2 = b1 + 60000

        await db.upsert_aggregate(b1, "1m", "error", "failed_to_ping", None, 1)
        await db.upsert_aggregate(b2, "1m", "error", "failed_to_ping", None, 2)

        rows = await db.get_aggregates("1m", b1, b2 + 60000)
        assert len(rows) >= 2
        assert rows[0]["count"] <= rows[-1]["count"]

    async def test_meta_kv(self, db):
        await db.set_meta("test_key", "test_value")
        val = await db.get_meta("test_key")
        assert val == "test_value"

        val = await db.get_meta("nonexistent")
        assert val is None
