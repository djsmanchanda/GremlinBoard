from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from gremlinboard_api.api.routes.runtime import runtime_status
from gremlinboard_api.db import get_session
from gremlinboard_api.repositories.board import BoardRepository, serialize_widget
from gremlinboard_api.schemas.contracts import (
    DevtoolsActionRead,
    DevtoolsEventSummaryRead,
    DevtoolsProviderCacheRead,
    DevtoolsProviderRead,
    DevtoolsQueueRead,
    DevtoolsReplayRead,
    DevtoolsSubscriberRead,
    DevtoolsWebsocketRead,
    PresenceSource,
    RuntimeDevtoolsSnapshotRead,
    RuntimePressureRead,
)


router = APIRouter(prefix="/devtools", tags=["devtools"])


@router.get("/snapshot", response_model=RuntimeDevtoolsSnapshotRead)
async def devtools_snapshot(
    request: Request,
    recent_events: int = Query(default=80, ge=10, le=200),
    session: AsyncSession = Depends(get_session),
) -> RuntimeDevtoolsSnapshotRead:
    presence = getattr(request.app.state, "presence_manager", None)
    if presence is not None:
        await presence.record_activity(PresenceSource.SYSTEM_PANEL)

    runtime = await runtime_status(request, session)
    event_snapshot = request.app.state.event_bus.snapshot(recent_limit=recent_events)
    provider_snapshot = await request.app.state.provider_registry.runtime.activity_snapshot()
    generation_queue = request.app.state.generation_pipeline.queue_status()

    subscribers = [
        DevtoolsSubscriberRead(
            id=subscriber.id,
            kind=subscriber.kind,
            queue_depth=subscriber.queue_depth,
            max_queue_size=subscriber.max_queue_size,
            dropped_events=subscriber.dropped_events,
            categories=subscriber.categories,
            event_types=subscriber.event_types,
            health=_subscriber_health(
                queue_depth=subscriber.queue_depth,
                max_queue_size=subscriber.max_queue_size,
                dropped_events=subscriber.dropped_events,
            ),
        )
        for subscriber in event_snapshot.subscribers
    ]
    queues = DevtoolsQueueRead(
        event_bus_queue_depth=event_snapshot.stats.queued_event_count,
        websocket_queue_depth=event_snapshot.stats.websocket_queue_depth,
        internal_queue_depth=event_snapshot.stats.internal_queue_depth,
        generation_queue_depth=int(generation_queue["queue_depth"]),
        generation_queued_input_count=int(generation_queue["queued_input_count"]),
        generation_worker_running=bool(generation_queue["worker_running"]),
        max_subscriber_queue_depth=event_snapshot.stats.max_subscriber_queue_depth,
        dropped_event_count=event_snapshot.stats.dropped_event_count,
        websocket_dropped_event_count=event_snapshot.stats.websocket_dropped_event_count,
        observability_sink_error=getattr(request.app.state.observability, "last_event_sink_error", None),
        health=_queue_health(
            dropped_events=event_snapshot.stats.dropped_event_count,
            max_depth=event_snapshot.stats.max_subscriber_queue_depth,
            subscriber_count=event_snapshot.stats.subscriber_count,
        ),
        durability_notes={
            "ephemeral": "May be dropped under websocket backpressure; snapshot fallback restores board state.",
            "timeline": "Persisted by observability sink when emitted as timeline events.",
            "state": "Domain tables remain source of truth; event is an indexable signal after commit.",
        },
    )
    providers = DevtoolsProviderRead(
        providers=provider_snapshot["providers"],
        cache=DevtoolsProviderCacheRead.model_validate(provider_snapshot["cache"]),
        degradation=runtime.provider_degradation,
    )

    async with request.app.state.session_factory() as session:
        stale_widget_count, error_widget_count = await _widget_pressure(session, request.app.state.runtime_manager.board_id)

    return RuntimeDevtoolsSnapshotRead(
        observed_at=datetime.now(timezone.utc),
        runtime=runtime,
        replay=DevtoolsReplayRead(
            history_size=event_snapshot.stats.history_size,
            replay_oldest_sequence=event_snapshot.stats.replay_oldest_sequence,
            latest_sequence=event_snapshot.stats.latest_sequence,
            replay_event_count=event_snapshot.stats.replay_event_count,
            replay_miss_count=event_snapshot.stats.replay_miss_count,
            stream_reset_count=event_snapshot.stats.stream_reset_count,
            snapshot_fallback_count=event_snapshot.stats.snapshot_fallback_count,
            recent_events=[_event_summary(event) for event in event_snapshot.recent_events],
        ),
        websocket=DevtoolsWebsocketRead(
            subscriber_count=request.app.state.event_bus.websocket_subscriber_count,
            subscribers=[subscriber for subscriber in subscribers if subscriber.kind == "websocket"],
            stream_reset_count=event_snapshot.stats.stream_reset_count,
            replay_miss_count=event_snapshot.stats.replay_miss_count,
            snapshot_fallback_count=event_snapshot.stats.snapshot_fallback_count,
        ),
        queues=queues,
        providers=providers,
        pressure=RuntimePressureRead(
            queue_health=queues.health,
            replay_pressure="pressure"
            if event_snapshot.stats.replay_miss_count or event_snapshot.stats.snapshot_fallback_count
            else "ok",
            subscriber_pressure=_subscriber_pressure(subscribers),
            provider_pressure="degraded" if runtime.provider_degradation else "ok",
            stale_widget_count=stale_widget_count,
            error_widget_count=error_widget_count,
        ),
    )


@router.post("/actions/{action}", response_model=DevtoolsActionRead)
async def run_devtools_action(action: str, request: Request) -> DevtoolsActionRead:
    if action == "clear-replay":
        cleared = request.app.state.event_bus.clear_replay_history()
        return DevtoolsActionRead(status="ok", action=action, detail={"cleared_events": cleared})
    if action == "force-snapshot":
        published = await request.app.state.runtime_manager.force_board_snapshot()
        return DevtoolsActionRead(status="ok", action=action, detail={"published": published})
    if action == "simulate-stream-reset":
        event = await request.app.state.event_bus.publish_event(
            "stream.reset",
            category="system",
            source={"component": "devtools"},
            visibility="websocket",
            persistence="ephemeral",
            replayable=False,
            payload={"reason": "devtools_simulation"},
            message="devtools simulated stream reset",
        )
        return DevtoolsActionRead(status="ok", action=action, detail={"sequence": event.sequence})
    raise HTTPException(status_code=404, detail="unknown devtools action")


def _subscriber_health(
    *,
    queue_depth: int,
    max_queue_size: int,
    dropped_events: int,
) -> Literal["ok", "pressure", "overflow"]:
    if dropped_events > 0:
        return "overflow"
    if max_queue_size > 0 and queue_depth >= max_queue_size * 0.75:
        return "pressure"
    return "ok"


def _queue_health(
    *,
    dropped_events: int,
    max_depth: int,
    subscriber_count: int,
) -> Literal["ok", "pressure", "overflow"]:
    if dropped_events > 0:
        return "overflow"
    if subscriber_count > 0 and max_depth >= 48:
        return "pressure"
    return "ok"


def _subscriber_pressure(subscribers: list[DevtoolsSubscriberRead]) -> Literal["ok", "pressure", "overflow"]:
    if any(subscriber.health == "overflow" for subscriber in subscribers):
        return "overflow"
    if any(subscriber.health == "pressure" for subscriber in subscribers):
        return "pressure"
    return "ok"


async def _widget_pressure(session: AsyncSession, board_id: str) -> tuple[int, int]:
    repository = BoardRepository(session)
    widgets = await repository.list_widgets(board_id)
    stale_widget_count = 0
    error_widget_count = 0
    for widget in widgets:
        serialized = serialize_widget(widget)
        if serialized.lifecycle_state == "error":
            error_widget_count += 1
        state_meta = serialized.state.get("meta") if isinstance(serialized.state, dict) else None
        if isinstance(state_meta, dict) and state_meta.get("stale"):
            stale_widget_count += 1
    return stale_widget_count, error_widget_count


def _event_summary(event: Any) -> DevtoolsEventSummaryRead:
    payload = event.payload if isinstance(event.payload, dict) else {}
    payload_json = json.dumps(payload, default=str, sort_keys=True)
    return DevtoolsEventSummaryRead(
        id=event.id,
        sequence=event.sequence,
        type=event.event_type,
        category=event.category,
        level=event.level,
        visibility=event.visibility,
        persistence=event.persistence,
        replayable=event.replayable,
        source=event.source,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
        created_at=event.created_at,
        payload_keys=sorted(str(key) for key in payload.keys()),
        payload_size=len(payload_json),
    )
