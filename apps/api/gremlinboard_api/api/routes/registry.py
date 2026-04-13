from __future__ import annotations

from fastapi import APIRouter, Request

from gremlinboard_api.schemas.contracts import WidgetRegistryEntry


router = APIRouter(prefix="/registry", tags=["registry"])


@router.get("/widgets", response_model=dict[str, WidgetRegistryEntry])
async def list_widgets(request: Request) -> dict[str, WidgetRegistryEntry]:
    registry = request.app.state.registry
    plugins = {plugin.widget_id: plugin for plugin in await request.app.state.plugin_manager.list_plugins()}
    return {
        widget_id: WidgetRegistryEntry(
            manifest=entry.manifest,
            config_schema=entry.config_schema,
            plugin=plugins.get(widget_id),
        )
        for widget_id, entry in registry.as_response().items()
    }
