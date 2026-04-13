from __future__ import annotations

from fastapi import APIRouter, Request

from gremlinboard_api.schemas.contracts import HealthRead


router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthRead)
async def healthcheck(request: Request) -> HealthRead:
    registry = request.app.state.registry
    runtime = request.app.state.runtime_manager
    return HealthRead(status="ok", registry_size=registry.size, active_runners=runtime.active_count)
