import time

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("/ranking")
async def get_device_ranking(
    request: Request,
    since: int = Query(..., description="Unix timestamp ms"),
    until: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    until = until or int(time.time() * 1000)
    db = request.app.state.db
    devices = await db.get_device_ranking(since, until, limit)
    return {"devices": devices}


@router.get("/detail")
async def get_device_detail(
    request: Request,
    device: str = Query(..., description="Device name"),
    since: int = Query(..., description="Unix timestamp ms"),
    until: int | None = Query(None),
):
    until = until or int(time.time() * 1000)
    db = request.app.state.db
    detail = await db.get_device_detail(device, since, until)
    return detail
