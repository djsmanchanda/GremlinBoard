from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from gremlinboard_api.config import settings
from gremlinboard_api.db import get_session
from gremlinboard_api.repositories.board import BoardRepository, serialize_board, serialize_widget
from gremlinboard_api.schemas.contracts import (
    BoardRead,
    LifecycleState,
    WidgetConfigUpdate,
    WidgetCreate,
    WidgetInstanceRead,
    WidgetReorder,
    WidgetResize,
    PresenceSource,
)
from gremlinboard_api.validation.config_schema import ConfigValidationError, normalize_config


router = APIRouter(prefix="/board", tags=["board"])


async def _read_board(session: AsyncSession) -> BoardRead:
    repository = BoardRepository(session)
    board = await repository.ensure_board(settings.default_board_id, "GremlinBoard")
    widgets = await repository.list_widgets(settings.default_board_id)
    return serialize_board(board, widgets)


@router.get("", response_model=BoardRead)
async def get_board(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BoardRead:
    presence = getattr(request.app.state, "presence_manager", None)
    if presence is not None:
        await presence.record_activity(PresenceSource.BOARD_FETCH)
    return await _read_board(session)


@router.post("/widgets", response_model=WidgetInstanceRead)
async def add_widget(
    payload: WidgetCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WidgetInstanceRead:
    registry = request.app.state.registry
    runtime = request.app.state.runtime_manager
    if not await request.app.state.plugin_manager.is_enabled(payload.widget_id):
        raise HTTPException(status_code=400, detail="widget plugin is disabled or not installed")
    try:
        loaded = registry.get(payload.widget_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if payload.size not in loaded.manifest.allowed_sizes:
        raise HTTPException(status_code=400, detail="requested size is not supported by this widget")
    try:
        normalized_config = normalize_config(loaded.config_schema, payload.config)
    except ConfigValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc

    repository = BoardRepository(session)
    owner_user_id = request.state.auth_context.user.id
    await repository.ensure_board(settings.default_board_id, "GremlinBoard", owner_user_id=owner_user_id)
    widgets = await repository.list_widgets(settings.default_board_id)
    expires_at = None
    if loaded.manifest.lifecycle_policy.expires and loaded.manifest.lifecycle_policy.default_ttl_seconds:
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=loaded.manifest.lifecycle_policy.default_ttl_seconds
        )
    record = await repository.create_widget(
        board_id=settings.default_board_id,
        owner_user_id=owner_user_id,
        widget_id=payload.widget_id,
        title=payload.title or loaded.manifest.name,
        size=payload.size,
        position_index=len(widgets),
        config=normalized_config,
        lifecycle_state=LifecycleState.CREATED,
        expires_at=expires_at,
    )
    await runtime.start_widget(record.id)
    fresh = await repository.get_widget(record.id)
    if fresh is None:
        raise HTTPException(status_code=500, detail="widget was created but could not be reloaded")
    return serialize_widget(fresh)


@router.patch("/widgets/reorder", response_model=BoardRead)
async def reorder_widgets(
    payload: WidgetReorder,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BoardRead:
    repository = BoardRepository(session)
    await repository.reorder_widgets(settings.default_board_id, payload.ordered_ids)
    await request.app.state.runtime_manager.publish_board_snapshot()
    return await _read_board(session)


@router.patch("/widgets/{widget_instance_id}/size", response_model=WidgetInstanceRead)
async def resize_widget(
    widget_instance_id: str,
    payload: WidgetResize,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WidgetInstanceRead:
    repository = BoardRepository(session)
    record = await repository.get_widget(widget_instance_id)
    if record is None:
        raise HTTPException(status_code=404, detail="widget instance not found")

    manifest = request.app.state.registry.get(record.widget_id).manifest
    if payload.size not in manifest.allowed_sizes:
        raise HTTPException(status_code=400, detail="requested size is not supported by this widget")

    updated = await repository.update_widget(record, size=payload.size)
    await request.app.state.runtime_manager.publish_board_snapshot()
    return serialize_widget(updated)


@router.patch("/widgets/{widget_instance_id}", response_model=WidgetInstanceRead)
async def update_widget(
    widget_instance_id: str,
    payload: WidgetConfigUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WidgetInstanceRead:
    repository = BoardRepository(session)
    record = await repository.get_widget(widget_instance_id)
    if record is None:
        raise HTTPException(status_code=404, detail="widget instance not found")

    current_config = serialize_widget(record).config
    next_config = payload.config if payload.config is not None else current_config
    try:
        loaded = request.app.state.registry.get(record.widget_id)
        normalized_config = normalize_config(loaded.config_schema, next_config)
    except ConfigValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    updated = await repository.update_widget(
        record,
        title=payload.title or record.title,
        config=normalized_config,
    )
    await request.app.state.runtime_manager.update_widget_config(widget_instance_id, normalized_config)
    return serialize_widget(updated)


@router.post("/widgets/{widget_instance_id}/start", response_model=BoardRead)
async def start_widget(
    widget_instance_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BoardRead:
    await request.app.state.runtime_manager.start_widget(widget_instance_id)
    return await _read_board(session)


@router.post("/widgets/{widget_instance_id}/stop", response_model=BoardRead)
async def stop_widget(
    widget_instance_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BoardRead:
    await request.app.state.runtime_manager.stop_widget(widget_instance_id)
    return await _read_board(session)


@router.post("/widgets/{widget_instance_id}/refresh", response_model=BoardRead)
async def refresh_widget(
    widget_instance_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BoardRead:
    await request.app.state.runtime_manager.refresh_widget(widget_instance_id)
    return await _read_board(session)


@router.delete("/widgets/{widget_instance_id}", response_model=BoardRead)
async def remove_widget(
    widget_instance_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BoardRead:
    await request.app.state.runtime_manager.stop_widget(widget_instance_id, removed=True)
    return await _read_board(session)


@router.websocket("/stream")
async def board_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    event_bus = websocket.app.state.event_bus
    presence = getattr(websocket.app.state, "presence_manager", None)
    presence_token = await presence.websocket_connected() if presence is not None else None
    last_seq = _parse_last_seq(websocket.query_params.get("last_seq"))
    queue = event_bus.subscribe(kind="websocket")
    try:
        if last_seq is not None and event_bus.can_replay(last_seq):
            for event in event_bus.replay(after_sequence=last_seq):
                if not await _send_json(websocket, event.to_websocket_message()):
                    return
        else:
            if last_seq is not None:
                event_bus.record_replay_miss()
            event_bus.record_snapshot_fallback()
            async with websocket.app.state.session_factory() as session:
                snapshot = await _read_board(session)
                runtime = getattr(websocket.app.state, "runtime_manager", None)
                if runtime is not None:
                    runtime.note_board_snapshot(snapshot)
                if not await _send_json(
                    websocket,
                    {
                        "type": "board.snapshot",
                        "sequence": event_bus.latest_sequence,
                        "payload": snapshot.model_dump(mode="json"),
                    },
                ):
                    return

        while True:
            event = await queue.get()
            if event.event_type == "stream.reset":
                event_bus.record_snapshot_fallback()
                async with websocket.app.state.session_factory() as session:
                    snapshot = await _read_board(session)
                    runtime = getattr(websocket.app.state, "runtime_manager", None)
                    if runtime is not None:
                        runtime.note_board_snapshot(snapshot)
                    if not await _send_json(
                        websocket,
                        {
                            "type": "board.snapshot",
                            "sequence": event_bus.latest_sequence,
                            "payload": snapshot.model_dump(mode="json"),
                        },
                    ):
                        return
                continue
            if not await _send_json(websocket, event.to_websocket_message()):
                return
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(queue)
        if presence is not None:
            await presence.websocket_disconnected(presence_token)


def _parse_last_seq(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


async def _send_json(websocket: WebSocket, payload: dict[str, object]) -> bool:
    try:
        await asyncio.wait_for(websocket.send_json(payload), timeout=5.0)
        return True
    except Exception:
        return False
