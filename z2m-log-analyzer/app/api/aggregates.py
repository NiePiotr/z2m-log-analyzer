import time

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/aggregates", tags=["aggregates"])

VALID_WINDOWS = {"1m", "5m", "1h", "24h"}


@router.get("")
async def get_aggregates(
    request: Request,
    window: str = Query(..., description="1m|5m|1h|24h"),
    since: int = Query(..., description="Unix timestamp ms"),
    until: int | None = Query(None, description="Unix timestamp ms"),
    level: str | None = Query(None),
    category: str | None = None,
    device: str | None = None,
):
    if window not in VALID_WINDOWS:
        raise HTTPException(status_code=400, detail=f"Invalid window: {window}. Use one of {VALID_WINDOWS}")

    until = until or int(time.time() * 1000)
    db = request.app.state.db
    data = await db.get_aggregates(
        window, since, until, level=level,
        category=category, device=device,
    )
    return {"window": window, "data": data}


@router.get("/totals")
async def get_aggregate_totals(
    request: Request,
    window: str = Query(..., description="1m|5m|1h|24h"),
    since: int = Query(..., description="Unix timestamp ms"),
    until: int | None = Query(None),
    device: str | None = None,
):
    if window not in VALID_WINDOWS:
        raise HTTPException(status_code=400, detail=f"Invalid window: {window}. Use one of {VALID_WINDOWS}")

    until = until or int(time.time() * 1000)
    db = request.app.state.db
    data = await db.get_aggregate_totals(window, since, until, device=device)
    return {"window": window, "data": data}
