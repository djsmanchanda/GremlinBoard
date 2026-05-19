from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from gremlinboard_api.db import get_session
from gremlinboard_api.repositories.board import BoardRepository, serialize_runtime_log, serialize_widget
from gremlinboard_api.schemas.contracts import (
    ProviderDegradationRead,
    RuntimeLogRead,
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
    repository = BoardRepository(session)
    widgets = await repository.list_widgets(request.app.state.runtime_manager.board_id)
    provider_degradation = _provider_degradation(widgets)
    event_stats = request.app.state.event_bus.stats()
    has_widget_error = any(widget.lifecycle_state == "error" for widget in widgets)
    state = "degraded" if has_widget_error or provider_degradation else "active"
    if request.app.state.runtime_manager.active_count == 0 and not has_widget_error and not provider_degradation:
        state = "idle"

    return RuntimeStatusRead(
        state=state,
        active_runners=request.app.state.runtime_manager.active_count,
        websocket_subscribers=request.app.state.event_bus.websocket_subscriber_count,
        monitor_cadence_seconds=request.app.state.runtime_manager.monitor_interval_seconds,
        provider_degradation=provider_degradation,
        queue_depth=event_stats.queued_event_count,
        dropped_event_count=event_stats.dropped_event_count,
        replay_event_count=event_stats.replay_event_count,
        registry_size=request.app.state.registry.size,
        widgets_total=len(widgets),
        runners=[
            RuntimeRunnerStatusRead.model_validate(runner)
            for runner in request.app.state.runtime_manager.runner_statuses()
        ],
        startup_recovery=RuntimeStartupRecoveryRead.model_validate(
            request.app.state.runtime_manager.startup_recovery
        ),
    )


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
