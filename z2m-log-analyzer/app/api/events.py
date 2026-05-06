import csv
import io
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
async def list_events(
    request: Request,
    since: int | None = Query(None, description="Unix timestamp ms"),
    until: int | None = Query(None, description="Unix timestamp ms"),
    level: str | None = Query(None, description="error|warning|info|debug"),
    category: str | None = None,
    device: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    db = request.app.state.db
    events = await db.get_events(
        since_ts=since, until_ts=until, level=level,
        category=category, device=device, limit=limit, offset=offset,
    )
    total = await db.get_event_count(
        since_ts=since, until_ts=until, level=level,
        category=category, device=device,
    )
    return {"events": events, "total": total, "limit": limit, "offset": offset}


@router.get("/export.csv")
async def export_csv(
    request: Request,
    since: int | None = Query(None),
    until: int | None = Query(None),
    level: str | None = Query(None),
    category: str | None = None,
    device: str | None = None,
):
    db = request.app.state.db
    events = await db.get_events(
        since_ts=since, until_ts=until, level=level,
        category=category, device=device, limit=10000, offset=0,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "level", "category", "device", "message"])
    for e in events:
        writer.writerow([
            e["ts"], e["level"], e["category"],
            e.get("device", ""), e.get("raw_message", ""),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=z2m_events.csv"},
    )
