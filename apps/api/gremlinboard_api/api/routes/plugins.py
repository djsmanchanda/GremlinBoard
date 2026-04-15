from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from gremlinboard_api.schemas.contracts import (
    WidgetPluginInstallRequest,
    WidgetPluginRead,
    WidgetPluginRollbackRequest,
    WidgetPluginToggleRequest,
    WidgetPluginUpdateRequest,
    WidgetPluginVersionRead,
)


router = APIRouter(prefix="/plugins", tags=["plugins"])


@router.get("", response_model=list[WidgetPluginRead])
async def list_plugins(request: Request) -> list[WidgetPluginRead]:
    return await request.app.state.plugin_manager.list_plugins()


@router.get("/{widget_id}/versions", response_model=list[WidgetPluginVersionRead])
async def list_versions(widget_id: str, request: Request) -> list[WidgetPluginVersionRead]:
    return await request.app.state.plugin_manager.list_versions(widget_id)


@router.post("/install", response_model=WidgetPluginRead)
async def install_plugin(payload: WidgetPluginInstallRequest, request: Request) -> WidgetPluginRead:
    try:
        plugin = await request.app.state.plugin_manager.install_widget(payload)
        await request.app.state.runtime_manager.publish_board_snapshot()
        await request.app.state.event_bus.publish({"type": "registry.updated", "payload": {"widget_id": plugin.widget_id}})
        return plugin
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{widget_id}/update", response_model=WidgetPluginRead)
async def update_plugin(
    widget_id: str,
    payload: WidgetPluginUpdateRequest,
    request: Request,
) -> WidgetPluginRead:
    try:
        plugin = await request.app.state.plugin_manager.update_widget(widget_id, payload)
        await request.app.state.runtime_manager.restart_widgets_by_widget_id(widget_id, reason="plugin updated")
        await request.app.state.event_bus.publish({"type": "registry.updated", "payload": {"widget_id": widget_id}})
        return plugin
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{widget_id}/rollback", response_model=WidgetPluginRead)
async def rollback_plugin(
    widget_id: str,
    payload: WidgetPluginRollbackRequest,
    request: Request,
) -> WidgetPluginRead:
    try:
        plugin = await request.app.state.plugin_manager.rollback_widget(widget_id, payload.version)
        await request.app.state.runtime_manager.restart_widgets_by_widget_id(widget_id, reason="plugin rolled back")
        await request.app.state.event_bus.publish({"type": "registry.updated", "payload": {"widget_id": widget_id}})
        return plugin
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{widget_id}/toggle", response_model=WidgetPluginRead)
async def toggle_plugin(
    widget_id: str,
    payload: WidgetPluginToggleRequest,
    request: Request,
) -> WidgetPluginRead:
    try:
        plugin = await request.app.state.plugin_manager.set_enabled(widget_id, payload.enabled)
        if payload.enabled:
            await request.app.state.runtime_manager.restart_widgets_by_widget_id(widget_id, reason="plugin enabled")
        else:
            await request.app.state.runtime_manager.pause_widgets_by_widget_id(widget_id, reason="plugin disabled")
        return plugin
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{widget_id}", response_model=WidgetPluginRead)
async def uninstall_plugin(widget_id: str, request: Request) -> WidgetPluginRead:
    try:
        plugin = await request.app.state.plugin_manager.uninstall_widget(widget_id)
        await request.app.state.runtime_manager.publish_board_snapshot()
        await request.app.state.event_bus.publish({"type": "registry.updated", "payload": {"widget_id": widget_id}})
        return plugin
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reload")
async def reload_registry(request: Request) -> dict[str, str]:
    await request.app.state.plugin_manager.reload_registry()
    await request.app.state.runtime_manager.publish_board_snapshot()
    await request.app.state.event_bus.publish({"type": "registry.updated", "payload": {}})
    return {"status": "reloaded"}
