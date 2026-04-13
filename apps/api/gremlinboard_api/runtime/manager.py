from __future__ import annotations

import asyncio
import importlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gremlinboard_api.registry.loader import WidgetRegistry
from gremlinboard_api.repositories.board import BoardRepository, serialize_board, serialize_runtime_log
from gremlinboard_api.runtime.base import BaseWidgetService
from gremlinboard_api.runtime.events import EventBus
from gremlinboard_api.schemas.contracts import LifecycleState, WidgetManifest


class RuntimeFailure(Exception):
    def __init__(self, *, event: str, message: str, context: dict[str, Any] | None = None):
        super().__init__(message)
        self.event = event
        self.message = message
        self.context = context or {}


@dataclass(slots=True)
class WidgetRunner:
    instance_id: str
    widget_id: str
    manifest: WidgetManifest
    config: dict[str, Any]
    stop_event: asyncio.Event
    service: BaseWidgetService | None = None
    task: asyncio.Task[None] | None = None
    restart_count: int = 0
    consecutive_failures: int = 0
    last_started_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    last_refresh_at: datetime | None = None
    pending_stop_reason: str | None = None


class RuntimeManager:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        registry: WidgetRegistry,
        event_bus: EventBus,
        board_id: str,
        is_widget_enabled: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.event_bus = event_bus
        self.board_id = board_id
        self.is_widget_enabled = is_widget_enabled
        self._runners: dict[str, WidgetRunner] = {}
        self._monitor_stop = asyncio.Event()
        self._monitor_task: asyncio.Task[None] | None = None

    @property
    def active_count(self) -> int:
        return len(self._runners)

    async def bootstrap(self) -> None:
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            await repository.ensure_board(self.board_id, "GremlinBoard")
            widgets = await repository.list_widgets(self.board_id)
            for widget in widgets:
                if widget.lifecycle_state in {
                    LifecycleState.PAUSED.value,
                    LifecycleState.REMOVED.value,
                    LifecycleState.EXPIRED.value,
                }:
                    continue
                await self.start_widget(widget.id)
        self._monitor_task = asyncio.create_task(self._monitor_loop(), name="gremlinboard-runtime-monitor")
        await self.publish_board_snapshot()

    async def shutdown(self) -> None:
        self._monitor_stop.set()
        if self._monitor_task is not None:
            await self._monitor_task
        for instance_id in list(self._runners.keys()):
            await self.stop_widget(instance_id, persist_state=False)

    async def start_widget(self, instance_id: str, *, force: bool = False) -> None:
        if not force and instance_id in self._runners:
            return
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            record = await repository.get_widget(instance_id)
            if record is None or record.is_removed:
                return
            if self.is_widget_enabled is not None and not await self.is_widget_enabled(record.widget_id):
                await repository.update_widget(
                    record,
                    lifecycle_state=LifecycleState.PAUSED,
                    status_message="plugin disabled",
                )
                await self.publish_board_snapshot()
                return
            try:
                loaded = self.registry.get(record.widget_id)
            except KeyError:
                await repository.update_widget(
                    record,
                    lifecycle_state=LifecycleState.ERROR,
                    status_message="plugin unavailable",
                    last_error="widget is not available in the registry",
                )
                await self.publish_board_snapshot()
                return
            runner = WidgetRunner(
                instance_id=record.id,
                widget_id=record.widget_id,
                manifest=loaded.manifest,
                config=json.loads(record.config_json or "{}"),
                stop_event=asyncio.Event(),
                restart_count=record.restart_count,
                consecutive_failures=record.consecutive_failures,
            )
            self._runners[record.id] = runner
            runner.task = asyncio.create_task(self._run_widget_loop(runner), name=f"widget-runner-{record.id}")

    async def stop_widget(
        self,
        instance_id: str,
        *,
        removed: bool = False,
        final_state: LifecycleState | None = None,
        persist_state: bool = True,
        reason: str | None = None,
    ) -> None:
        runner = self._runners.pop(instance_id, None)
        if runner is not None:
            runner.pending_stop_reason = reason
            runner.stop_event.set()
            if runner.task is not None and runner.task is not asyncio.current_task():
                await runner.task

        if persist_state:
            async with self.session_factory() as session:
                repository = BoardRepository(session)
                record = await repository.get_widget(instance_id)
                if record is None:
                    return
                await repository.update_widget(
                    record,
                    lifecycle_state=final_state or (LifecycleState.REMOVED if removed else LifecycleState.PAUSED),
                    status_message=reason or record.status_message,
                    is_removed=removed if removed else None,
                )
            await self.publish_board_snapshot()

    async def restart_widget(self, instance_id: str, *, reason: str) -> None:
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            record = await repository.get_widget(instance_id)
            if record is None or record.is_removed:
                return
            await self.stop_widget(instance_id, persist_state=False, reason=reason)
            await self.start_widget(instance_id, force=True)
            await self.log(
                level="warning",
                event="runner.restarted",
                widget_instance_id=instance_id,
                widget_id=record.widget_id,
                message=reason,
                context={"reason": reason},
            )

    async def refresh_widget(self, instance_id: str) -> None:
        runner = self._runners.get(instance_id)
        if runner is None:
            return
        await self._refresh_runner(runner)
        await self.publish_board_snapshot()

    async def update_widget_config(self, instance_id: str, config: dict[str, Any]) -> None:
        runner = self._runners.get(instance_id)
        if runner is not None:
            runner.config = config
            if runner.service is not None:
                await runner.service.set_config(config)
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            record = await repository.get_widget(instance_id)
            if record is not None:
                await repository.update_widget(record, config=config)
        await self.refresh_widget(instance_id)

    async def pause_widgets_by_widget_id(self, widget_id: str, *, reason: str) -> None:
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            records = await repository.list_widget_instances_by_widget_id(widget_id)
        for record in records:
            await self.stop_widget(record.id, final_state=LifecycleState.PAUSED, reason=reason)

    async def restart_widgets_by_widget_id(self, widget_id: str, *, reason: str) -> None:
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            records = await repository.list_widget_instances_by_widget_id(widget_id)
        for record in records:
            if record.lifecycle_state in {
                LifecycleState.RUNNING.value,
                LifecycleState.CREATED.value,
                LifecycleState.ERROR.value,
            }:
                await self.restart_widget(record.id, reason=reason)

    async def publish_board_snapshot(self) -> None:
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            board = await repository.ensure_board(self.board_id, "GremlinBoard")
            widgets = await repository.list_widgets(self.board_id)
            snapshot = serialize_board(board, widgets)
            await self.event_bus.publish(
                {
                    "type": "board.snapshot",
                    "payload": snapshot.model_dump(mode="json"),
                }
            )

    async def log(
        self,
        *,
        level: str,
        event: str,
        widget_instance_id: str | None,
        widget_id: str | None,
        message: str,
        context: dict[str, Any],
    ) -> None:
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            record = await repository.create_runtime_log(
                widget_instance_id=widget_instance_id,
                widget_id=widget_id,
                level=level,
                event=event,
                message=message,
                context=context,
            )
        await self.event_bus.publish(
            {
                "type": "runtime.log",
                "payload": serialize_runtime_log(record).model_dump(mode="json"),
            }
        )

    async def _run_widget_loop(self, runner: WidgetRunner) -> None:
        try:
            while not runner.stop_event.is_set():
                try:
                    await self._run_single_attempt(runner)
                    break
                except RuntimeFailure as exc:
                    should_retry = await self._handle_failure(runner, exc)
                    if not should_retry or runner.stop_event.is_set():
                        break
                    backoff = runner.manifest.runtime_policy.retry_backoff_seconds * max(runner.consecutive_failures, 1)
                    try:
                        await asyncio.wait_for(runner.stop_event.wait(), timeout=backoff)
                    except TimeoutError:
                        pass
        finally:
            await self._safe_stop_service(runner)
            await self.publish_board_snapshot()

    async def _run_single_attempt(self, runner: WidgetRunner) -> None:
        runner.service = self._build_service(
            manifest=runner.manifest,
            instance_id=runner.instance_id,
            config=runner.config,
        )
        try:
            await asyncio.wait_for(
                runner.service.start(),
                timeout=runner.manifest.runtime_policy.start_timeout_seconds,
            )
        except TimeoutError as exc:
            raise RuntimeFailure(
                event="runner.start_timeout",
                message="service start timed out",
                context={"timeout_seconds": runner.manifest.runtime_policy.start_timeout_seconds},
            ) from exc

        runner.service.mark_started()
        runner.last_started_at = datetime.now(timezone.utc)
        runner.last_heartbeat_at = runner.last_started_at
        await self._persist_running_state(runner, status_message="running")
        await self.log(
            level="info",
            event="runner.started",
            widget_instance_id=runner.instance_id,
            widget_id=runner.widget_id,
            message="widget service started",
            context={"widget_id": runner.widget_id, "version": runner.manifest.version},
        )

        await self._refresh_runner(runner)
        while not runner.stop_event.is_set():
            interval = (
                runner.manifest.refresh_policy.interval_seconds
                if runner.manifest.refresh_policy.mode != "manual"
                else min(runner.manifest.runtime_policy.heartbeat_timeout_seconds, 30)
            )
            try:
                await asyncio.wait_for(runner.stop_event.wait(), timeout=max(interval, 1))
            except TimeoutError:
                pass
            if runner.stop_event.is_set():
                break
            if runner.manifest.refresh_policy.mode != "manual":
                await self._refresh_runner(runner)

    async def _refresh_runner(self, runner: WidgetRunner) -> None:
        if runner.service is None:
            raise RuntimeFailure(event="runner.missing_service", message="service is not available for refresh")
        now = datetime.now(timezone.utc)
        try:
            state = await asyncio.wait_for(
                runner.service.refresh(),
                timeout=runner.manifest.runtime_policy.refresh_timeout_seconds,
            )
            health = await asyncio.wait_for(
                runner.service.health(),
                timeout=runner.manifest.runtime_policy.refresh_timeout_seconds,
            )
        except TimeoutError as exc:
            raise RuntimeFailure(
                event="runner.refresh_timeout",
                message="service refresh timed out",
                context={"timeout_seconds": runner.manifest.runtime_policy.refresh_timeout_seconds},
            ) from exc

        runner.last_heartbeat_at = now
        runner.last_refresh_at = now
        runner.consecutive_failures = 0
        lifecycle_state = LifecycleState.RUNNING
        expires_at = False
        status_message = str(health.get("status", "running"))
        if health.get("expired"):
            lifecycle_state = LifecycleState.EXPIRED
            expires_value = health.get("expires_at")
            if isinstance(expires_value, str):
                expires_at = datetime.fromisoformat(expires_value)

        async with self.session_factory() as session:
            repository = BoardRepository(session)
            record = await repository.get_widget(runner.instance_id)
            if record is None:
                return
            await repository.update_widget(
                record,
                state=state,
                lifecycle_state=lifecycle_state,
                freshness_at=now,
                last_heartbeat=now,
                status_message=status_message,
                expires_at=expires_at,
                clear_error=True,
                service_started_at=runner.last_started_at,
                service_uptime_seconds=self._uptime_seconds(runner),
                restart_count=runner.restart_count,
                consecutive_failures=runner.consecutive_failures,
            )

        if lifecycle_state == LifecycleState.EXPIRED:
            await self.log(
                level="info",
                event="runner.expired",
                widget_instance_id=runner.instance_id,
                widget_id=runner.widget_id,
                message="widget expired and was stopped",
                context={"widget_id": runner.widget_id},
            )
            await self.stop_widget(
                runner.instance_id,
                final_state=LifecycleState.EXPIRED,
                reason="expired",
            )

    async def _persist_running_state(self, runner: WidgetRunner, *, status_message: str) -> None:
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            record = await repository.get_widget(runner.instance_id)
            if record is None:
                return
            await repository.update_widget(
                record,
                lifecycle_state=LifecycleState.RUNNING,
                status_message=status_message,
                service_started_at=runner.last_started_at,
                service_uptime_seconds=self._uptime_seconds(runner),
                restart_count=runner.restart_count,
                consecutive_failures=runner.consecutive_failures,
            )

    async def _handle_failure(self, runner: WidgetRunner, error: RuntimeFailure) -> bool:
        runner.consecutive_failures += 1
        max_retries = runner.manifest.runtime_policy.max_retries
        should_retry = runner.consecutive_failures <= max_retries and not runner.stop_event.is_set()
        if should_retry:
            runner.restart_count += 1
        await self._safe_stop_service(runner)
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            record = await repository.get_widget(runner.instance_id)
            if record is not None:
                await repository.update_widget(
                    record,
                    lifecycle_state=LifecycleState.ERROR,
                    status_message="retrying" if should_retry else "runtime failed",
                    last_error=error.message,
                    service_uptime_seconds=self._uptime_seconds(runner),
                    restart_count=runner.restart_count,
                    consecutive_failures=runner.consecutive_failures,
                )
        await self.log(
            level="warning" if should_retry else "error",
            event=error.event,
            widget_instance_id=runner.instance_id,
            widget_id=runner.widget_id,
            message=error.message,
            context={
                **error.context,
                "retry": should_retry,
                "restart_count": runner.restart_count,
                "consecutive_failures": runner.consecutive_failures,
            },
        )
        if not should_retry:
            return False
        return True

    async def _monitor_loop(self) -> None:
        while not self._monitor_stop.is_set():
            try:
                await asyncio.wait_for(self._monitor_stop.wait(), timeout=5)
            except TimeoutError:
                pass
            if self._monitor_stop.is_set():
                break
            await self._monitor_runtime_health()

    async def _monitor_runtime_health(self) -> None:
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            widgets = await repository.list_widgets(self.board_id)
        records = {record.id: record for record in widgets}
        registered_widget_ids = {entry.manifest.id for entry in self.registry.all()}

        for runner in list(self._runners.values()):
            record = records.get(runner.instance_id)
            if record is None or record.is_removed:
                await self.stop_widget(runner.instance_id, persist_state=False, reason="stale cleanup")
                continue
            if self.is_widget_enabled is not None and not await self.is_widget_enabled(runner.widget_id):
                await self.pause_widgets_by_widget_id(runner.widget_id, reason="plugin disabled")
                continue
            if runner.widget_id not in registered_widget_ids:
                await self.stop_widget(runner.instance_id, final_state=LifecycleState.PAUSED, reason="plugin unavailable")
                continue
            if runner.last_heartbeat_at is not None and runner.manifest.refresh_policy.mode != "manual":
                heartbeat_age = (now - runner.last_heartbeat_at).total_seconds()
                if heartbeat_age > runner.manifest.runtime_policy.heartbeat_timeout_seconds:
                    await self.restart_widget(runner.instance_id, reason="heartbeat timeout")
                    continue

        for record in records.values():
            if record.expires_at is not None and record.expires_at <= now and record.lifecycle_state != LifecycleState.EXPIRED.value:
                await self.stop_widget(record.id, final_state=LifecycleState.EXPIRED, reason="expired")
                continue
            if record.lifecycle_state == LifecycleState.ERROR.value and record.last_heartbeat is not None:
                stale_age = (now - record.last_heartbeat).total_seconds()
                manifest = self.registry.get(record.widget_id).manifest if record.widget_id in registered_widget_ids else None
                if manifest is not None and stale_age > manifest.runtime_policy.stale_after_seconds:
                    await self.stop_widget(record.id, final_state=LifecycleState.PAUSED, reason="stale cleanup")

    async def _safe_stop_service(self, runner: WidgetRunner) -> None:
        if runner.service is None:
            return
        try:
            await runner.service.stop()
        except Exception as exc:  # pragma: no cover
            await self.log(
                level="error",
                event="runner.stop_error",
                widget_instance_id=runner.instance_id,
                widget_id=runner.widget_id,
                message=str(exc),
                context={"widget_id": runner.widget_id},
            )
        finally:
            runner.service = None

    def _build_service(
        self, *, manifest: WidgetManifest, instance_id: str, config: dict[str, Any]
    ) -> BaseWidgetService:
        module = importlib.import_module(manifest.service.module)
        service_class = getattr(module, manifest.service.class_name)
        service = service_class(instance_id=instance_id, manifest=manifest, config=config)
        if not isinstance(service, BaseWidgetService):
            raise TypeError(f"widget service {manifest.id} must inherit BaseWidgetService")
        return service

    @staticmethod
    def _uptime_seconds(runner: WidgetRunner) -> int:
        if runner.last_started_at is None:
            return 0
        return max(int((datetime.now(timezone.utc) - runner.last_started_at).total_seconds()), 0)
