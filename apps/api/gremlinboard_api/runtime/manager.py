from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gremlinboard_api.models.tables import WidgetInstanceRecord
from gremlinboard_api.registry.loader import WidgetRegistry
from gremlinboard_api.repositories.board import BoardRepository, serialize_board
from gremlinboard_api.runtime.base import BaseWidgetService
from gremlinboard_api.runtime.events import EventBus
from gremlinboard_api.schemas.contracts import LifecycleState, WidgetManifest


@dataclass(slots=True)
class WidgetRunner:
    instance_id: str
    manifest: WidgetManifest
    service: BaseWidgetService
    stop_event: asyncio.Event
    task: asyncio.Task[None] | None = None


class RuntimeManager:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        registry: WidgetRegistry,
        event_bus: EventBus,
        board_id: str,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.event_bus = event_bus
        self.board_id = board_id
        self._runners: dict[str, WidgetRunner] = {}

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
        await self.publish_board_snapshot()

    async def start_widget(self, instance_id: str) -> None:
        if instance_id in self._runners:
            return
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            record = await repository.get_widget(instance_id)
            if record is None or record.is_removed:
                return
            loaded = self.registry.get(record.widget_id)
            service = self._build_service(
                manifest=loaded.manifest,
                instance_id=record.id,
                config=json.loads(record.config_json or "{}"),
            )
            runner = WidgetRunner(
                instance_id=record.id,
                manifest=loaded.manifest,
                service=service,
                stop_event=asyncio.Event(),
            )
            self._runners[record.id] = runner
            runner.task = asyncio.create_task(self._run_widget(record.id), name=f"widget-runner-{record.id}")

    async def stop_widget(
        self,
        instance_id: str,
        *,
        removed: bool = False,
        final_state: LifecycleState | None = None,
        persist_state: bool = True,
    ) -> None:
        runner = self._runners.pop(instance_id, None)
        if runner is not None:
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
                    is_removed=removed if removed else None,
                )
            await self.publish_board_snapshot()

    async def refresh_widget(self, instance_id: str) -> None:
        runner = self._runners.get(instance_id)
        if runner is None:
            return
        await self._refresh_runner(runner)
        await self.publish_board_snapshot()

    async def update_widget_config(self, instance_id: str, config: dict[str, Any]) -> None:
        runner = self._runners.get(instance_id)
        if runner is not None:
            await runner.service.set_config(config)
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            record = await repository.get_widget(instance_id)
            if record is not None:
                await repository.update_widget(record, config=config)
        await self.refresh_widget(instance_id)

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

    async def _run_widget(self, instance_id: str) -> None:
        runner = self._runners[instance_id]
        interval = max(runner.manifest.refresh_policy.interval_seconds, 1)

        try:
            await runner.service.start()
            runner.service.mark_started()
            async with self.session_factory() as session:
                repository = BoardRepository(session)
                record = await repository.get_widget(instance_id)
                if record is not None:
                    await repository.update_widget(
                        record,
                        lifecycle_state=LifecycleState.RUNNING,
                        status_message="running",
                    )

            await self._refresh_runner(runner)
            while not runner.stop_event.is_set():
                wait_seconds = interval if runner.manifest.refresh_policy.mode != "manual" else 3600
                try:
                    await asyncio.wait_for(runner.stop_event.wait(), timeout=wait_seconds)
                except TimeoutError:
                    pass
                if runner.stop_event.is_set():
                    break
                await self._refresh_runner(runner)
        except Exception as exc:  # pragma: no cover
            async with self.session_factory() as session:
                repository = BoardRepository(session)
                record = await repository.get_widget(instance_id)
                if record is not None:
                    await repository.update_widget(
                        record,
                        lifecycle_state=LifecycleState.ERROR,
                        status_message="runtime error",
                        last_error=str(exc),
                    )
        finally:
            try:
                await runner.service.stop()
            finally:
                await self.publish_board_snapshot()

    async def _refresh_runner(self, runner: WidgetRunner) -> None:
        now = datetime.now(timezone.utc)
        state = await runner.service.refresh()
        health = await runner.service.health()
        lifecycle_state = LifecycleState.RUNNING
        expires_at = False
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
                status_message=health.get("status", "running"),
                expires_at=expires_at,
                clear_error=True,
            )

        if lifecycle_state == LifecycleState.EXPIRED:
            await self.stop_widget(runner.instance_id, final_state=LifecycleState.EXPIRED)

    def _build_service(
        self, *, manifest: WidgetManifest, instance_id: str, config: dict[str, Any]
    ) -> BaseWidgetService:
        module = importlib.import_module(manifest.service.module)
        service_class = getattr(module, manifest.service.class_name)
        service = service_class(instance_id=instance_id, manifest=manifest, config=config)
        if not isinstance(service, BaseWidgetService):
            raise TypeError(f"widget service {manifest.id} must inherit BaseWidgetService")
        return service

    async def shutdown(self) -> None:
        for instance_id in list(self._runners.keys()):
            await self.stop_widget(instance_id, persist_state=False)
