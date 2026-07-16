from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gremlinboard_api.registry.loader import WidgetRegistry
from gremlinboard_api.repositories.board import BoardRepository, serialize_board, serialize_runtime_log
from gremlinboard_api.runtime.base import BaseWidgetService, RefreshDirective, ServiceContext
from gremlinboard_api.runtime.process_service import ProcessWidgetService
from gremlinboard_api.runtime.events import EventBus
from gremlinboard_api.schemas.contracts import (
    BoardPatchRead,
    BoardRead,
    LifecycleState,
    RuntimeEventCategory,
    RuntimeEventLevel,
    RuntimeEventPersistence,
    RuntimeEventSource,
    RuntimeEventVisibility,
    PythonServiceTarget,
    WidgetManifest,
)

if TYPE_CHECKING:
    from gremlinboard_api.services.presence import PresenceManager


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
    refresh_directive: RefreshDirective | None = None
    operation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RuntimeManager:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        registry: WidgetRegistry,
        event_bus: EventBus,
        board_id: str,
        is_widget_enabled: Callable[[str], Awaitable[bool]] | None = None,
        service_context: ServiceContext | None = None,
        capture_metrics: Callable[[], Awaitable[None]] | None = None,
        presence_manager: PresenceManager | None = None,
        monitor_interval_seconds: int = 5,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.event_bus = event_bus
        self.board_id = board_id
        self.is_widget_enabled = is_widget_enabled
        self.service_context = service_context
        self.capture_metrics = capture_metrics
        self.presence_manager = presence_manager
        self._runners: dict[str, WidgetRunner] = {}
        self._widget_locks: dict[str, asyncio.Lock] = {}
        self._monitor_stop = asyncio.Event()
        self._monitor_task: asyncio.Task[None] | None = None
        self._monitor_interval_seconds = self._coerce_monitor_interval(monitor_interval_seconds)
        self._isolate_generated = os.environ.get("GREMLINBOARD_ISOLATE_GENERATED", "1") != "0"
        self._startup_recovery: dict[str, Any] = {
            "recovered_widgets": 0,
            "skipped_widgets": 0,
            "orphan_widgets": 0,
            "registry_size": 0,
            "checked_at": None,
        }
        self._last_published_board: BoardRead | None = None

    @property
    def active_count(self) -> int:
        return len(self._runners)

    @property
    def monitor_interval_seconds(self) -> int:
        return self._monitor_interval_seconds

    def update_monitor_interval(self, seconds: int) -> None:
        self._monitor_interval_seconds = self._coerce_monitor_interval(seconds)

    @property
    def startup_recovery(self) -> dict[str, Any]:
        return dict(self._startup_recovery)

    def runner_statuses(self) -> list[dict[str, Any]]:
        return [
            {
                "instance_id": runner.instance_id,
                "widget_id": runner.widget_id,
                "manifest_version": runner.manifest.version,
                "running": runner.task is not None and not runner.task.done(),
                "refresh_mode": self._resolve_refresh_directive(runner).mode,
                "refresh_interval_seconds": self._resolve_refresh_directive(runner).interval_seconds,
                "restart_count": runner.restart_count,
                "consecutive_failures": runner.consecutive_failures,
                "last_started_at": runner.last_started_at,
                "last_heartbeat_at": runner.last_heartbeat_at,
                "last_refresh_at": runner.last_refresh_at,
            }
            for runner in self._runners.values()
        ]

    async def bootstrap(self) -> None:
        recovered_widgets = 0
        skipped_widgets = 0
        orphan_widgets = 0
        checked_at = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            await repository.ensure_board(self.board_id, "GremlinBoard")
            widgets = await repository.list_widgets(self.board_id)
            registered_widget_ids = {entry.manifest.id for entry in self.registry.all()}
            for widget in widgets:
                if widget.lifecycle_state in {
                    LifecycleState.PAUSED.value,
                    LifecycleState.REMOVED.value,
                    LifecycleState.EXPIRED.value,
                }:
                    skipped_widgets += 1
                    continue
                if widget.widget_id not in registered_widget_ids:
                    orphan_widgets += 1
                await self.start_widget(widget.id)
                recovered_widgets += 1
        self._startup_recovery = {
            "recovered_widgets": recovered_widgets,
            "skipped_widgets": skipped_widgets,
            "orphan_widgets": orphan_widgets,
            "registry_size": self.registry.size,
            "checked_at": checked_at,
        }
        await self.log(
            level="info" if orphan_widgets == 0 else "warning",
            event="runtime.startup_recovery.completed",
            widget_instance_id=None,
            widget_id=None,
            message="runtime startup recovery completed",
            context={**self.startup_recovery, "checked_at": checked_at.isoformat()},
        )
        self._monitor_task = asyncio.create_task(self._monitor_loop(), name="gremlinboard-runtime-monitor")
        await self.publish_board_snapshot()

    async def shutdown(self) -> None:
        self._monitor_stop.set()
        if self._monitor_task is not None:
            await self._monitor_task
        for instance_id in list(self._runners.keys()):
            await self.stop_widget(instance_id, persist_state=False)

    async def start_widget(self, instance_id: str, *, force: bool = False) -> None:
        async with self._widget_lock(instance_id):
            await self._start_widget_unlocked(instance_id, force=force)

    async def _start_widget_unlocked(self, instance_id: str, *, force: bool = False) -> None:
        if not force and instance_id in self._runners:
            return
        if force and instance_id in self._runners:
            await self._stop_widget_unlocked(instance_id, persist_state=False, reason="replaced")
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
        async with self._widget_lock(instance_id):
            await self._stop_widget_unlocked(
                instance_id,
                removed=removed,
                final_state=final_state,
                persist_state=persist_state,
                reason=reason,
            )

    async def _stop_widget_unlocked(
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
        async with self._widget_lock(instance_id):
            async with self.session_factory() as session:
                repository = BoardRepository(session)
                record = await repository.get_widget(instance_id)
                if record is None or record.is_removed:
                    return
            await self._stop_widget_unlocked(instance_id, persist_state=False, reason=reason)
            await self._start_widget_unlocked(instance_id, force=True)
            await self.log(
                level="warning",
                event="runner.restarted",
                widget_instance_id=instance_id,
                widget_id=record.widget_id,
                message=reason,
                context={"reason": reason},
            )

    async def refresh_widget(self, instance_id: str) -> None:
        expired = False
        async with self._widget_lock(instance_id):
            runner = self._runners.get(instance_id)
            if runner is None:
                return
            lifecycle_state = await self._refresh_runner(runner, force=True, stop_on_expired=False)
            expired = lifecycle_state == LifecycleState.EXPIRED
        await self.publish_board_snapshot()
        if expired:
            await self.stop_widget(instance_id, final_state=LifecycleState.EXPIRED, reason="expired")

    async def update_widget_config(self, instance_id: str, config: dict[str, Any]) -> None:
        expired = False
        should_start = False
        async with self._widget_lock(instance_id):
            runner = self._runners.get(instance_id)
            if runner is not None:
                async with runner.operation_lock:
                    runner.config = config
                    if runner.service is not None:
                        await runner.service.invalidate_cache()
                        await runner.service.set_config(config)
            async with self.session_factory() as session:
                repository = BoardRepository(session)
                record = await repository.get_widget(instance_id)
                if record is not None:
                    await repository.update_widget(record, config=config)
                    should_start = record.lifecycle_state in {
                        LifecycleState.CREATED.value,
                        LifecycleState.ERROR.value,
                        LifecycleState.EXPIRED.value,
                    }
            runner = self._runners.get(instance_id)
            if runner is not None:
                lifecycle_state = await self._refresh_runner(runner, force=True, stop_on_expired=False)
                expired = lifecycle_state == LifecycleState.EXPIRED
            elif should_start:
                await self._start_widget_unlocked(instance_id, force=True)
        await self.publish_board_snapshot()
        if expired:
            await self.stop_widget(instance_id, final_state=LifecycleState.EXPIRED, reason="expired")

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
        if self.event_bus.websocket_subscriber_count == 0:
            return
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            board = await repository.ensure_board(self.board_id, "GremlinBoard")
            widgets = await repository.list_widgets(self.board_id)
            snapshot = serialize_board(board, widgets, blueprints_by_widget_id=self.registry.blueprints_by_widget_id())
            snapshot = snapshot.model_copy(update={"boot_id": self.event_bus.boot_id})
            previous = self._last_published_board
            self._last_published_board = snapshot
            if previous is not None:
                patch = self._diff_board_snapshot(previous, snapshot)
                await self.event_bus.publish_event(
                    "board.patch",
                    category=RuntimeEventCategory.BOARD,
                    source=RuntimeEventSource(component="runtime_manager", board_id=self.board_id),
                    payload=patch.model_dump(mode="json"),
                    visibility=RuntimeEventVisibility.WEBSOCKET,
                    persistence=RuntimeEventPersistence.EPHEMERAL,
                )
                return
            await self.event_bus.publish_event(
                "board.snapshot",
                category=RuntimeEventCategory.BOARD,
                source=RuntimeEventSource(component="runtime_manager", board_id=self.board_id),
                payload=snapshot.model_dump(mode="json"),
                visibility=RuntimeEventVisibility.WEBSOCKET,
                persistence=RuntimeEventPersistence.EPHEMERAL,
            )

    async def force_board_snapshot(self) -> bool:
        if self.event_bus.websocket_subscriber_count == 0:
            return False
        self._last_published_board = None
        await self.publish_board_snapshot()
        return True

    def note_board_snapshot(self, snapshot: BoardRead) -> None:
        self._last_published_board = snapshot

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
        await self.event_bus.publish_event(
            self._normalize_log_event_type(event),
            category=self._log_event_category(event),
            level=RuntimeEventLevel(level),
            message=message,
            source=RuntimeEventSource(
                component="runtime_manager",
                board_id=self.board_id,
                widget_instance_id=widget_instance_id,
                widget_id=widget_id,
            ),
            payload=serialize_runtime_log(record).model_dump(mode="json"),
            visibility=RuntimeEventVisibility.BOTH,
            persistence=RuntimeEventPersistence.EPHEMERAL,
        )

    async def _run_widget_loop(self, runner: WidgetRunner) -> None:
        try:
            while not runner.stop_event.is_set():
                try:
                    await self._run_single_attempt(runner)
                    break
                except RuntimeFailure as exc:
                    should_retry = await self._handle_failure(runner, exc)
                except Exception as exc:
                    should_retry = await self._handle_failure(
                        runner,
                        RuntimeFailure(
                            event="runner.crashed",
                            message=str(exc),
                            context={"error_type": type(exc).__name__},
                        ),
                    )
                if not should_retry or runner.stop_event.is_set():
                    break
                backoff = runner.manifest.runtime_policy.retry_backoff_seconds * max(runner.consecutive_failures, 1)
                try:
                    await asyncio.wait_for(runner.stop_event.wait(), timeout=backoff)
                except TimeoutError:
                    pass
        finally:
            await self._safe_stop_service(runner)
            if runner.stop_event.is_set() and self._runners.get(runner.instance_id) is runner:
                self._runners.pop(runner.instance_id, None)
            await self.publish_board_snapshot()

    async def _run_single_attempt(self, runner: WidgetRunner) -> None:
        async with runner.operation_lock:
            if runner.stop_event.is_set():
                return
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
            except Exception as exc:
                raise RuntimeFailure(
                    event="runner.start_failed",
                    message=str(exc),
                    context={"error_type": type(exc).__name__},
                ) from exc

            if runner.stop_event.is_set():
                return
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

        if runner.stop_event.is_set():
            return
        await self._refresh_runner(runner, force=False)
        await self.publish_board_snapshot()
        while not runner.stop_event.is_set():
            directive = self._resolve_refresh_directive(runner)
            interval = (
                directive.interval_seconds
                if directive.mode != "manual"
                else min(runner.manifest.runtime_policy.heartbeat_timeout_seconds, 30)
            )
            try:
                await asyncio.wait_for(runner.stop_event.wait(), timeout=max(interval, 1))
            except TimeoutError:
                pass
            if runner.stop_event.is_set():
                break
            if directive.mode != "manual":
                if await self._scheduled_work_paused():
                    continue
                await self._refresh_runner(runner, force=False)
                await self.publish_board_snapshot()

    async def _refresh_runner(
        self,
        runner: WidgetRunner,
        *,
        force: bool,
        stop_on_expired: bool = True,
    ) -> LifecycleState | None:
        async with runner.operation_lock:
            if runner.stop_event.is_set() or self._runners.get(runner.instance_id) is not runner:
                return None
            if runner.service is None:
                raise RuntimeFailure(event="runner.missing_service", message="service is not available for refresh")
            now = datetime.now(timezone.utc)
            try:
                state = await asyncio.wait_for(
                    runner.service.refresh(force=force),
                    timeout=runner.manifest.runtime_policy.refresh_timeout_seconds,
                )
                if runner.stop_event.is_set() or self._runners.get(runner.instance_id) is not runner:
                    return None
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
            except Exception as exc:
                raise RuntimeFailure(
                    event="runner.refresh_failed",
                    message=str(exc),
                    context={"error_type": type(exc).__name__},
                ) from exc

            if runner.stop_event.is_set() or self._runners.get(runner.instance_id) is not runner:
                return None
            runner.last_heartbeat_at = now
            runner.last_refresh_at = now
            runner.refresh_directive = runner.service.get_refresh_directive()
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
                    return None
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
            if stop_on_expired:
                runner.stop_event.set()
        return lifecycle_state

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
                await asyncio.wait_for(self._monitor_stop.wait(), timeout=self._monitor_interval_seconds)
            except TimeoutError:
                pass
            if self._monitor_stop.is_set():
                break
            try:
                await self._monitor_runtime_health()
                if self.capture_metrics is not None and not await self._scheduled_work_paused():
                    await self.capture_metrics()
            except Exception as exc:  # pragma: no cover - defensive background task guard
                try:
                    await self.log(
                        level="error",
                        event="runtime.monitor_failed",
                        widget_instance_id=None,
                        widget_id=None,
                        message=str(exc),
                        context={"error_type": type(exc).__name__},
                    )
                except Exception:
                    pass

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
            expires_at = self._coerce_utc(record.expires_at) if record.expires_at is not None else None
            if expires_at is not None and expires_at <= now and record.lifecycle_state != LifecycleState.EXPIRED.value:
                await self.stop_widget(record.id, final_state=LifecycleState.EXPIRED, reason="expired")
                continue
            if record.lifecycle_state == LifecycleState.ERROR.value and record.last_heartbeat is not None:
                stale_age = (now - self._coerce_utc(record.last_heartbeat)).total_seconds()
                manifest = self.registry.get(record.widget_id).manifest if record.widget_id in registered_widget_ids else None
                if manifest is not None and stale_age > manifest.runtime_policy.stale_after_seconds:
                    await self.stop_widget(record.id, final_state=LifecycleState.PAUSED, reason="stale cleanup")

    async def _safe_stop_service(self, runner: WidgetRunner) -> None:
        async with runner.operation_lock:
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
        loaded = self.registry.get(manifest.id)
        if manifest.service.kind == "process":
            return ProcessWidgetService(
                instance_id=instance_id,
                manifest=manifest,
                config=config,
                widget_root=loaded.root_dir,
                service_context=self.service_context,
            )
        if not isinstance(manifest.service, PythonServiceTarget):
            raise TypeError(f"unsupported widget service kind for {manifest.id}: {manifest.service.kind}")
        if self._isolate_generated and not loaded.is_core:
            return ProcessWidgetService(
                instance_id=instance_id,
                manifest=manifest,
                config=config,
                widget_root=loaded.root_dir,
                service_context=self.service_context,
                command=self._python_process_host_command(manifest),
                cwd=Path(__file__).resolve().parents[2],
            )
        expected_module = f"widgets.{manifest.id}.backend"
        if manifest.service.module != expected_module:
            raise TypeError(f"widget service module for {manifest.id} must be '{expected_module}'")
        widgets_parent = str(self.registry.widgets_dir.parent)
        if widgets_parent not in sys.path:
            sys.path.insert(0, widgets_parent)
        module = importlib.import_module(manifest.service.module)
        service_class = getattr(module, manifest.service.class_name)
        service = service_class(
            instance_id=instance_id,
            manifest=manifest,
            config=config,
            service_context=self.service_context,
        )
        if not isinstance(service, BaseWidgetService):
            raise TypeError(f"widget service {manifest.id} must inherit BaseWidgetService")
        return service

    def _python_process_host_command(self, manifest: WidgetManifest) -> list[str]:
        if not isinstance(manifest.service, PythonServiceTarget):
            raise TypeError("python process host requires a python service manifest")
        api_root = Path(__file__).resolve().parents[2]
        widgets_parent = self.registry.widgets_dir.resolve().parent
        bootstrap = (
            "import runpy,sys;"
            "sys.path.insert(0,sys.argv.pop(1));"
            "runpy.run_module('gremlinboard_api.runtime.python_process_host',run_name='__main__')"
        )
        return [
            sys.executable,
            "-I",
            "-c",
            bootstrap,
            str(api_root),
            str(widgets_parent),
            manifest.id,
            manifest.service.class_name,
        ]

    @staticmethod
    def _uptime_seconds(runner: WidgetRunner) -> int:
        if runner.last_started_at is None:
            return 0
        return max(int((datetime.now(timezone.utc) - runner.last_started_at).total_seconds()), 0)

    @staticmethod
    def _coerce_monitor_interval(seconds: int) -> int:
        return min(max(seconds, 15), 300)

    @staticmethod
    def _coerce_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _config_interval_override(config: dict[str, Any]) -> int | None:
        value = config.get("refresh_interval_seconds")
        if isinstance(value, int) and value > 0 and not isinstance(value, bool):
            return value
        return None

    def _resolve_refresh_directive(self, runner: WidgetRunner) -> RefreshDirective:
        behavior = str(runner.config.get("refresh_behavior") or "auto")
        interval_override = self._config_interval_override(runner.config)
        service_directive = runner.refresh_directive
        manifest_mode = runner.manifest.refresh_policy.mode
        manifest_interval = runner.manifest.refresh_policy.interval_seconds

        if behavior in {"manual", "interval", "live"}:
            return RefreshDirective(
                mode=behavior,
                interval_seconds=interval_override or manifest_interval,
                reason="widget config override",
            )
        if service_directive is not None:
            return RefreshDirective(
                mode=service_directive.mode,
                interval_seconds=interval_override or service_directive.interval_seconds,
                reason=service_directive.reason,
            )
        return RefreshDirective(
            mode=manifest_mode,
            interval_seconds=interval_override or manifest_interval,
            reason="manifest refresh policy",
        )

    @staticmethod
    def _diff_board_snapshot(previous: BoardRead, current: BoardRead) -> BoardPatchRead:
        previous_by_id = {widget.id: widget for widget in previous.widgets}
        current_by_id = {widget.id: widget for widget in current.widgets}
        upserted_widgets = [
            widget
            for widget in current.widgets
            if previous_by_id.get(widget.id) != widget
        ]
        removed_widget_ids = [widget_id for widget_id in previous_by_id if widget_id not in current_by_id]
        previous_order = [widget.id for widget in previous.widgets]
        current_order = [widget.id for widget in current.widgets]
        return BoardPatchRead(
            board_id=current.id,
            name=current.name if current.name != previous.name else None,
            owner_user_id=current.owner_user_id if current.owner_user_id != previous.owner_user_id else None,
            upserted_widgets=upserted_widgets,
            removed_widget_ids=removed_widget_ids,
            ordered_widget_ids=current_order if current_order != previous_order else [],
        )

    def _widget_lock(self, instance_id: str) -> asyncio.Lock:
        lock = self._widget_locks.get(instance_id)
        if lock is None:
            lock = asyncio.Lock()
            self._widget_locks[instance_id] = lock
        return lock

    async def _scheduled_work_paused(self) -> bool:
        if self.presence_manager is None:
            return False
        return await self.presence_manager.should_pause_scheduled_work()

    @staticmethod
    def _normalize_log_event_type(event: str) -> str:
        if event.startswith("runner."):
            return f"widget.{event.removeprefix('runner.')}"
        return event

    @staticmethod
    def _log_event_category(event: str) -> RuntimeEventCategory:
        prefix = RuntimeManager._normalize_log_event_type(event).split(".", 1)[0]
        return RuntimeEventCategory(prefix)
