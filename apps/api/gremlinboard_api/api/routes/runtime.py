from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from gremlinboard_api.db import get_session
from gremlinboard_api.repositories.board import BoardRepository, serialize_runtime_log, serialize_widget
from gremlinboard_api.schemas.contracts import (
    PresenceSnapshotRead,
    PresenceSource,
    ProviderDegradationRead,
    RuntimeLogRead,
    RuntimePowerState,
    RuntimeStartupRecoveryRead,
    RuntimeStatusRead,
    RuntimeRunnerStatusRead,
)


router = APIRouter(prefix="/runtime", tags=["runtime"])


@router.get("/logs", response_model=list[RuntimeLogRead])
async def list_runtime_logs(
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
) -> list[RuntimeLogRead]:
    repository = BoardRepository(session)
    return [serialize_runtime_log(record) for record in await repository.list_runtime_logs(limit=limit)]


@router.get("/status", response_model=RuntimeStatusRead)
async def runtime_status(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> RuntimeStatusRead:
    await _record_runtime_presence(request)
    repository = BoardRepository(session)
    widgets = await repository.list_widgets(request.app.state.runtime_manager.board_id)
    provider_degradation = _provider_degradation(widgets)
    event_stats = request.app.state.event_bus.stats()
    agent_registry = getattr(request.app.state, "agent_registry", None)
    agent_summary = agent_registry.summary() if agent_registry is not None else None
    has_widget_error = any(widget.lifecycle_state == "error" for widget in widgets)
    has_agent_failure = bool(agent_summary and agent_summary.failed_agents)
    has_agent_activity = bool(agent_summary and (agent_summary.active_agents or agent_summary.waiting_for_review))
    degraded = has_widget_error or bool(provider_degradation) or has_agent_failure
    presence = await _presence_snapshot(
        request,
        degraded=degraded,
        reason="runtime errors present" if degraded else None,
    )
    state = presence.state.value if presence is not None else _legacy_state(
        active_count=request.app.state.runtime_manager.active_count,
        has_widget_error=has_widget_error,
        provider_degradation=provider_degradation,
        has_agent_activity=has_agent_activity,
        has_agent_failure=has_agent_failure,
    )

    return RuntimeStatusRead(
        state=state,
        presence=presence,
        active_runners=request.app.state.runtime_manager.active_count,
        websocket_subscribers=request.app.state.event_bus.websocket_subscriber_count,
        monitor_cadence_seconds=request.app.state.runtime_manager.monitor_interval_seconds,
        provider_degradation=provider_degradation,
        queue_depth=event_stats.queued_event_count,
        dropped_event_count=event_stats.dropped_event_count,
        replay_event_count=event_stats.replay_event_count,
        published_event_count=event_stats.published_event_count,
        replay_history_size=event_stats.history_size,
        replay_oldest_sequence=event_stats.replay_oldest_sequence,
        latest_sequence=event_stats.latest_sequence,
        stream_reset_count=event_stats.stream_reset_count,
        replay_miss_count=event_stats.replay_miss_count,
        snapshot_fallback_count=event_stats.snapshot_fallback_count,
        websocket_queue_depth=event_stats.websocket_queue_depth,
        internal_queue_depth=event_stats.internal_queue_depth,
        max_subscriber_queue_depth=event_stats.max_subscriber_queue_depth,
        websocket_dropped_event_count=event_stats.websocket_dropped_event_count,
        observability_sink_error=getattr(request.app.state.observability, "last_event_sink_error", None),
        registry_size=request.app.state.registry.size,
        widgets_total=len(widgets),
        active_agents=agent_summary.active_agents if agent_summary is not None else 0,
        agents_waiting_for_review=agent_summary.waiting_for_review if agent_summary is not None else 0,
        agents_failed=agent_summary.failed_agents if agent_summary is not None else 0,
        runners=[
            RuntimeRunnerStatusRead.model_validate(runner)
            for runner in request.app.state.runtime_manager.runner_statuses()
        ],
        startup_recovery=RuntimeStartupRecoveryRead.model_validate(
            request.app.state.runtime_manager.startup_recovery
        ),
    )


@router.post("/suspend", response_model=PresenceSnapshotRead)
async def suspend_runtime(request: Request) -> PresenceSnapshotRead:
    presence = request.app.state.presence_manager
    source = _presence_source_from_request(request, default=PresenceSource.OPERATOR)
    await presence.record_activity(source)
    return await presence.suspend(reason=f"{source.value} requested suspend")


@router.post("/resume", response_model=PresenceSnapshotRead)
async def resume_runtime(request: Request) -> PresenceSnapshotRead:
    presence = request.app.state.presence_manager
    return await presence.resume(source=_presence_source_from_request(request, default=PresenceSource.OPERATOR))


def _provider_degradation(widgets: list[Any]) -> list[ProviderDegradationRead]:
    degraded: list[ProviderDegradationRead] = []
    for widget in widgets:
        serialized = serialize_widget(widget)
        state = serialized.state
        meta = state.get("meta") if isinstance(state, dict) else None
        providers = meta.get("providers") if isinstance(meta, dict) else None
        if not isinstance(providers, list):
            continue
        for provider in providers:
            if not isinstance(provider, dict) or provider.get("status") != "degraded":
                continue
            degraded.append(
                ProviderDegradationRead(
                    provider_id=str(provider.get("provider_id") or "unknown"),
                    label=str(provider["label"]) if provider.get("label") is not None else None,
                    status="degraded",
                    error=str(provider["error"]) if provider.get("error") is not None else None,
                    widget_instance_id=serialized.id,
                    widget_id=serialized.widget_id,
                    fallback_used=bool(provider.get("fallback_used")),
                    stale=bool(meta.get("stale")) if isinstance(meta, dict) else False,
                )
            )
    return degraded


async def _record_runtime_presence(request: Request) -> None:
    presence = getattr(request.app.state, "presence_manager", None)
    if presence is None or request.headers.get("x-gremlin-presence-passive") == "true":
        return
    await presence.record_activity(_presence_source_from_request(request, default=PresenceSource.OPERATOR))


async def _presence_snapshot(
    request: Request,
    *,
    degraded: bool,
    reason: str | None,
) -> PresenceSnapshotRead | None:
    presence = getattr(request.app.state, "presence_manager", None)
    if presence is None:
        return None
    return await presence.snapshot(degraded=degraded, reason=reason)


def _presence_source_from_request(request: Request, *, default: PresenceSource) -> PresenceSource:
    raw = request.headers.get("x-gremlin-presence-source")
    if raw is None:
        return default
    try:
        return PresenceSource(raw)
    except ValueError:
        return default


def _legacy_state(
    *,
    active_count: int,
    has_widget_error: bool,
    provider_degradation: list[ProviderDegradationRead],
    has_agent_activity: bool,
    has_agent_failure: bool,
) -> str:
    if has_widget_error or provider_degradation or has_agent_failure:
        return RuntimePowerState.DEGRADED.value
    if active_count == 0 and not has_agent_activity:
        return RuntimePowerState.IDLE.value
    return RuntimePowerState.ACTIVE.value
