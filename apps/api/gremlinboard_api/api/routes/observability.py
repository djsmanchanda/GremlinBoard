from __future__ import annotations

from fastapi import APIRouter, Query, Request

from gremlinboard_api.schemas.contracts import ObservabilityOverviewRead, RuntimeLogRead


router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/overview", response_model=ObservabilityOverviewRead)
async def get_overview(
    request: Request,
    limit: int = Query(default=80, ge=20, le=500),
) -> ObservabilityOverviewRead:
    return await request.app.state.observability.overview(limit=limit)


@router.get("/logs", response_model=list[RuntimeLogRead])
async def get_logs(
    request: Request,
    limit: int = Query(default=100, ge=10, le=500),
    level: str | None = Query(default=None),
    widget_id: str | None = Query(default=None),
) -> list[RuntimeLogRead]:
    return await request.app.state.observability.list_logs(limit=limit, level=level, widget_id=widget_id)
