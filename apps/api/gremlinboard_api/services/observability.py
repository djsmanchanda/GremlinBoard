from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gremlinboard_api.repositories.board import BoardRepository, serialize_runtime_log, serialize_widget
from gremlinboard_api.repositories.platform import PlatformRepository, serialize_metric
from gremlinboard_api.schemas.contracts import (
    ObservabilityOverviewRead,
    RuntimeEventEnvelope,
    RuntimeEventPersistence,
    RuntimeLogRead,
    WidgetHealthRead,
)

if TYPE_CHECKING:
    from gremlinboard_api.registry.loader import WidgetRegistry
    from gremlinboard_api.runtime.events import EventBus
    from gremlinboard_api.runtime.manager import RuntimeManager
    from gremlinboard_api.services.agent_registry import AgentRegistry
    from gremlinboard_api.services.presence import PresenceManager
    from gremlinboard_api.services.system_settings import SystemSettingsService


class ObservabilityService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        board_id: str,
        registry: "WidgetRegistry",
        event_bus: "EventBus",
        runtime_manager: "RuntimeManager",
        settings_service: "SystemSettingsService",
        agent_registry: "AgentRegistry | None" = None,
        presence_manager: "PresenceManager | None" = None,
    ) -> None:
        self.session_factory = session_factory
        self.board_id = board_id
        self.registry = registry
        self.event_bus = event_bus
        self.runtime_manager = runtime_manager
        self.settings_service = settings_service
        self.agent_registry = agent_registry
        self.presence_manager = presence_manager
        self._event_queue: asyncio.Queue[RuntimeEventEnvelope] | None = None
        self._event_task: asyncio.Task[None] | None = None
        self.last_event_sink_error: str | None = None

    async def start_event_sink(self) -> None:
        if self._event_task is not None and not self._event_task.done():
            return
        self._event_queue = self.event_bus.subscribe(kind="internal", max_queue_size=256)
        self._event_task = asyncio.create_task(self._run_event_sink(), name="gremlinboard-observability-events")

    async def shutdown_event_sink(self) -> None:
        if self._event_queue is not None:
            try:
                await asyncio.wait_for(self._event_queue.join(), timeout=1.0)
            except TimeoutError:
                pass
            self.event_bus.unsubscribe(self._event_queue)
        if self._event_task is None:
            return
        self._event_task.cancel()
        try:
            await self._event_task
        except asyncio.CancelledError:
            pass
        finally:
            self._event_task = None
            self._event_queue = None

    async def capture_runtime_snapshot(self) -> None:
        settings = await self.settings_service.read()
        async with self.session_factory() as session:
            board_repository = BoardRepository(session)
            platform_repository = PlatformRepository(session)
            widgets = await board_repository.list_widgets(self.board_id)

            summary = {
                "registry_size": self.registry.size,
                "active_runners": self.runtime_manager.active_count,
                "widgets_total": len(widgets),
                "widgets_running": sum(1 for widget in widgets if widget.lifecycle_state == "running"),
                "widgets_error": sum(1 for widget in widgets if widget.lifecycle_state == "error"),
                "widgets_paused": sum(1 for widget in widgets if widget.lifecycle_state == "paused"),
                "widgets_expired": sum(1 for widget in widgets if widget.lifecycle_state == "expired"),
                "event_subscribers": self.event_bus.subscriber_count,
            }
            summary.update(await self._presence_summary())
            summary.update(_agent_summary(self.agent_registry))
            metric_batch = [
                {
                    "scope_type": "board",
                    "scope_id": self.board_id,
                    "metric_name": metric_name,
                    "metric_value": value,
                    "tags": {"board_id": self.board_id},
                }
                for metric_name, value in summary.items()
            ]

            for widget in widgets:
                freshness_age = 0
                if widget.freshness_at is not None:
                    freshness_at = _coerce_utc(widget.freshness_at)
                    freshness_age = max(
                        int((datetime.now(timezone.utc) - freshness_at).total_seconds()),
                        0,
                    )
                metric_batch.extend(
                    [
                        {
                            "scope_type": "widget",
                            "scope_id": widget.id,
                            "metric_name": "freshness_age_seconds",
                            "metric_value": freshness_age,
                            "tags": {"widget_id": widget.widget_id, "lifecycle_state": widget.lifecycle_state},
                        },
                        {
                            "scope_type": "widget",
                            "scope_id": widget.id,
                            "metric_name": "restart_count",
                            "metric_value": widget.restart_count,
                            "tags": {"widget_id": widget.widget_id},
                        },
                        {
                            "scope_type": "widget",
                            "scope_id": widget.id,
                            "metric_name": "service_uptime_seconds",
                            "metric_value": widget.service_uptime_seconds,
                            "tags": {"widget_id": widget.widget_id},
                        },
                    ]
                )

            await platform_repository.create_metrics(metric_batch)
            await platform_repository.trim_metrics(keep_latest=settings.runtime.metrics_retention_points)

    async def overview(self, *, limit: int = 80) -> ObservabilityOverviewRead:
        async with self.session_factory() as session:
            board_repository = BoardRepository(session)
            platform_repository = PlatformRepository(session)
            widgets = await board_repository.list_widgets(self.board_id)
            metrics = await platform_repository.list_metrics(limit=limit)
            logs = await board_repository.list_runtime_logs(limit=limit)

        summary = {
            "registry_size": self.registry.size,
            "active_runners": self.runtime_manager.active_count,
            "widgets_total": len(widgets),
            "widgets_running": sum(1 for widget in widgets if widget.lifecycle_state == "running"),
            "widgets_error": sum(1 for widget in widgets if widget.lifecycle_state == "error"),
            "widgets_paused": sum(1 for widget in widgets if widget.lifecycle_state == "paused"),
            "widgets_expired": sum(1 for widget in widgets if widget.lifecycle_state == "expired"),
            "event_subscribers": self.event_bus.subscriber_count,
        }
        summary.update(await self._presence_summary())
        summary.update(_agent_summary(self.agent_registry))

        widget_health = [
            WidgetHealthRead(
                widget_instance_id=widget.id,
                widget_id=widget.widget_id,
                title=widget.title,
                lifecycle_state=serialize_widget(widget).lifecycle_state,
                status_message=widget.status_message,
                freshness_at=widget.freshness_at,
                last_error=widget.last_error,
                restart_count=widget.restart_count,
                consecutive_failures=widget.consecutive_failures,
                service_uptime_seconds=widget.service_uptime_seconds,
            )
            for widget in widgets
        ]

        return ObservabilityOverviewRead(
            collected_at=datetime.now(timezone.utc),
            summary=summary,
            metrics=[serialize_metric(metric) for metric in metrics],
            widget_health=widget_health,
            timeline=[serialize_runtime_log(log) for log in logs],
        )

    async def _presence_summary(self) -> dict[str, int]:
        if self.presence_manager is None:
            return {
                "presence_active_websockets": 0,
                "runtime_power_state_active": 0,
                "runtime_power_state_idle": 0,
                "runtime_power_state_suspended": 0,
                "runtime_power_state_degraded": 0,
            }
        snapshot = await self.presence_manager.snapshot()
        return {
            "presence_active_websockets": snapshot.active_websocket_count,
            "runtime_power_state_active": 1 if snapshot.state == "active" else 0,
            "runtime_power_state_idle": 1 if snapshot.state == "idle" else 0,
            "runtime_power_state_suspended": 1 if snapshot.state == "suspended" else 0,
            "runtime_power_state_degraded": 1 if snapshot.state == "degraded" else 0,
        }

    async def list_logs(
        self,
        *,
        limit: int = 100,
        level: str | None = None,
        widget_id: str | None = None,
    ) -> list[RuntimeLogRead]:
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            records = await repository.list_runtime_logs(limit=limit)
        filtered = []
        for record in records:
            serialized = serialize_runtime_log(record)
            if level is not None and serialized.level != level:
                continue
            if widget_id is not None and serialized.widget_id != widget_id:
                continue
            filtered.append(serialized)
        return filtered

    async def log_platform_event(
        self,
        *,
        level: str,
        event: str,
        message: str,
        context: dict[str, Any],
    ) -> None:
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            record = await repository.create_runtime_log(
                widget_instance_id=None,
                widget_id=None,
                level=level,
                event=event,
                message=message,
                context=context,
            )
        await self.event_bus.publish_event(
            _typed_platform_event_type(event),
            category="system",
            level=level,
            message=message,
            source={"component": "observability", "board_id": self.board_id},
            payload=serialize_runtime_log(record).model_dump(mode="json"),
            persistence="ephemeral",
        )

    async def _run_event_sink(self) -> None:
        if self._event_queue is None:
            return
        while True:
            event = await self._event_queue.get()
            try:
                await self._handle_timeline_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive isolation for background persistence
                self.last_event_sink_error = str(exc)
            finally:
                self._event_queue.task_done()

    async def _handle_timeline_event(self, event: RuntimeEventEnvelope) -> None:
        if event.persistence not in {RuntimeEventPersistence.TIMELINE, RuntimeEventPersistence.STATE}:
            return
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            await repository.create_runtime_log(
                widget_instance_id=event.source.widget_instance_id,
                widget_id=event.source.widget_id,
                level=event.level.value,
                event=event.event_type,
                message=event.message or event.event_type,
                context={
                    "event_id": event.id,
                    "sequence": event.sequence,
                    "category": event.category.value,
                    "source": event.source.model_dump(mode="json"),
                    "correlation_id": event.correlation_id,
                    "causation_id": event.causation_id,
                    "payload": event.payload,
                },
            )


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _typed_platform_event_type(event: str) -> str:
    if event.startswith("system."):
        return event
    return f"system.{event.replace('.', '_')}"


def _agent_summary(agent_registry: Any | None) -> dict[str, int]:
    if agent_registry is None:
        return {
            "agent_registry_size": 0,
            "agents_active": 0,
            "agents_waiting_for_review": 0,
            "agents_failed": 0,
        }
    summary = agent_registry.summary()
    return {
        "agent_registry_size": summary.total_agents,
        "agents_active": summary.active_agents,
        "agents_waiting_for_review": summary.waiting_for_review,
        "agents_failed": summary.failed_agents,
    }
