from __future__ import annotations

from fastapi import APIRouter, Request

from gremlinboard_api.schemas.contracts import WidgetRegistryEntry


router = APIRouter(prefix="/registry", tags=["registry"])


@router.get("/widgets", response_model=dict[str, WidgetRegistryEntry])
async def list_widgets(request: Request) -> dict[str, WidgetRegistryEntry]:
    return request.app.state.registry.as_response()
