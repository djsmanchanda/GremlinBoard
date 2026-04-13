from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gremlinboard_api.repositories.board import BoardRepository, serialize_runtime_log, serialize_widget
from gremlinboard_api.repositories.platform import PlatformRepository, serialize_metric
from gremlinboard_api.schemas.contracts import ObservabilityOverviewRead, RuntimeLogRead, WidgetHealthRead

if TYPE_CHECKING:
    from gremlinboard_api.registry.loader import WidgetRegistry
    from gremlinboard_api.runtime.events import EventBus
    from gremlinboard_api.runtime.manager import RuntimeManager
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
    ) -> None:
        self.session_factory = session_factory
        self.board_id = board_id
        self.registry = registry
        self.event_bus = event_bus
        self.runtime_manager = runtime_manager
        self.settings_service = settings_service

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
        await self.event_bus.publish(
            {"type": "runtime.log", "payload": serialize_runtime_log(record).model_dump(mode="json")}
        )


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
