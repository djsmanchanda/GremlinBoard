from __future__ import annotations

import asyncio
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from gremlinboard_api.api.routes import agents, board, control, devtools, observability, plugins, runtime
from gremlinboard_api.config import settings
from gremlinboard_api.db import Base, get_session
from gremlinboard_api.providers.registry import ExternalProviderRegistry, ProviderRuntime
from gremlinboard_api.registry.loader import WidgetRegistry, load_registry
from gremlinboard_api.repositories.board import BoardRepository, serialize_runtime_log, serialize_widget
from gremlinboard_api.repositories.platform import PlatformRepository, serialize_metric
from gremlinboard_api.runtime.events import EventBus
from gremlinboard_api.runtime.manager import RuntimeManager
from gremlinboard_api.schemas.contracts import RuntimeLogRead, RuntimeMetricRead, WidgetInstanceRead
from gremlinboard_api.services.auth import AuthService
from gremlinboard_api.services.agent_registry import AgentRegistry
from gremlinboard_api.services.control_plane import ControlPlaneService
from gremlinboard_api.services.generation_pipeline import GenerationPipelineService
from gremlinboard_api.services.observability import ObservabilityService
from gremlinboard_api.services.plugin_manager import PluginManagerService
from gremlinboard_api.services.presence import PresenceManager
from gremlinboard_api.services.system_settings import SystemSettingsService


def build_widget_package(
    *,
    package_name: str,
    widget_id: str,
    version: str,
    class_name: str,
    backend_source: str,
    config_schema: dict[str, Any],
    description: str,
    renderer_target: str = "react",
    renderer_export_name: str = "TestRuntimeWidget",
    allowed_sizes: list[str] | None = None,
    refresh_mode: str = "manual",
    refresh_interval_seconds: int = 0,
    lifecycle_expires: bool = False,
    default_ttl_seconds: int | None = None,
    runtime_policy: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "manifest": {
            "id": widget_id,
            "version": version,
            "name": widget_id.replace("_", " ").title(),
            "category": "test",
            "description": description,
            "min_size": "2x2",
            "preferred_size": "2x2",
            "allowed_sizes": allowed_sizes or ["2x2"],
            "refresh_policy": {
                "mode": refresh_mode,
                "interval_seconds": refresh_interval_seconds,
            },
            "lifecycle_policy": {
                "stateful": True,
                "expires": lifecycle_expires,
                "default_ttl_seconds": default_ttl_seconds,
            },
            "runtime_policy": {
                "start_timeout_seconds": 5,
                "refresh_timeout_seconds": 5,
                "heartbeat_timeout_seconds": 10,
                "max_retries": 2,
                "retry_backoff_seconds": 1,
                "stale_after_seconds": 30,
                **(runtime_policy or {}),
            },
            "permissions": [],
            "renderer": {
                "target": renderer_target,
                "module": f"@widgets/{widget_id}/renderer",
                "export_name": renderer_export_name,
            },
            "service": {
                "module": f"widgets.{widget_id}.backend",
                "class_name": class_name,
            },
            "config_schema": "config.schema.json",
        },
        "config_schema": config_schema,
        "backend_source": backend_source,
        "renderer_source": (
            "import type { JSX } from 'react';\n\n"
            f"export function {renderer_export_name}(): JSX.Element | null {{\n"
            "  return null;\n"
            "}\n"
        ),
    }


def build_persistent_widget_package(*, package_name: str, widget_id: str, version: str) -> dict[str, Any]:
    backend_source = """
from __future__ import annotations

from gremlinboard_api.runtime.base import BaseWidgetService


class PersistentWidgetService(BaseWidgetService):
    async def start(self) -> None:
        self.state = await self.get_state()

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        return {"status": "running", "expired": False}

    async def get_state(self) -> dict[str, object]:
        return {
            "kind": "persistent",
            "manifest_version": self.manifest.version,
            "notes": self.config.get("notes", []),
            "instance_id": self.instance_id,
        }
""".strip()
    return build_widget_package(
        package_name=package_name,
        widget_id=widget_id,
        version=version,
        class_name="PersistentWidgetService",
        backend_source=backend_source,
        config_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "notes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "text"],
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                    "default": [],
                }
            },
            "additionalProperties": False,
        },
        description="Test widget with persisted note state.",
    )


def build_crashy_widget_package(*, package_name: str, widget_id: str) -> dict[str, Any]:
    backend_source = """
from __future__ import annotations

import time

from gremlinboard_api.runtime.base import BaseWidgetService


START_TIMESTAMPS: list[float] = []


class CrashyWidgetService(BaseWidgetService):
    async def start(self) -> None:
        START_TIMESTAMPS.append(time.monotonic())

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        return {"status": "running", "expired": False}

    async def get_state(self) -> dict[str, object]:
        raise RuntimeError(self.config.get("crash_message", "widget crashed during refresh"))
""".strip()
    return build_widget_package(
        package_name=package_name,
        widget_id=widget_id,
        version="1.0.0",
        class_name="CrashyWidgetService",
        backend_source=backend_source,
        config_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "crash_message": {"type": "string"},
            },
            "required": ["crash_message"],
            "additionalProperties": False,
        },
        description="Test widget that crashes on refresh to exercise retries.",
        refresh_mode="interval",
        refresh_interval_seconds=1,
        runtime_policy={
            "heartbeat_timeout_seconds": 5,
            "max_retries": 2,
            "retry_backoff_seconds": 1,
            "stale_after_seconds": 5,
        },
    )


def write_widget_package(widgets_dir: Path, widget_id: str, package: dict[str, Any]) -> None:
    widget_root = widgets_dir / widget_id
    widget_root.mkdir(parents=True, exist_ok=True)
    (widget_root / "manifest.json").write_text(json.dumps(package["manifest"], indent=2) + "\n", encoding="utf-8")
    (widget_root / "config.schema.json").write_text(
        json.dumps(package["config_schema"], indent=2) + "\n",
        encoding="utf-8",
    )
    (widget_root / "backend.py").write_text(package["backend_source"], encoding="utf-8")
    if package.get("blueprint") is not None:
        (widget_root / "view.blueprint.json").write_text(
            json.dumps(package["blueprint"], indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        (widget_root / "renderer.tsx").write_text(str(package["renderer_source"]), encoding="utf-8")
    (widget_root / "__init__.py").write_text('"""Test widget package."""\n', encoding="utf-8")


@dataclass(slots=True)
class RuntimeTestHarness:
    root: Path
    package_name: str
    widgets_dir: Path
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    registry: WidgetRegistry
    auth_service: AuthService
    settings_service: SystemSettingsService
    plugin_manager: PluginManagerService
    provider_runtime: ProviderRuntime
    provider_registry: ExternalProviderRegistry
    event_bus: EventBus
    presence_manager: PresenceManager
    agent_registry: AgentRegistry
    generation_pipeline: GenerationPipelineService
    control_plane: ControlPlaneService
    runtime_manager: RuntimeManager
    observability: ObservabilityService
    app: FastAPI
    client: AsyncClient

    @classmethod
    async def create(
        cls,
        *,
        startup_packages: list[dict[str, Any]] | None = None,
        monitor_interval_seconds: int = 60,
    ) -> RuntimeTestHarness:
        root = Path("data") / f"runtime-integration-{uuid4().hex}"
        package_name = "widgets"
        widgets_dir = root / package_name
        root.mkdir(parents=True, exist_ok=True)
        widgets_dir.mkdir(parents=True, exist_ok=True)
        (widgets_dir / "__init__.py").write_text('"""Runtime integration test widgets."""\n', encoding="utf-8")

        sys.path.insert(0, str(root.resolve()))

        for package in startup_packages or []:
            write_widget_package(widgets_dir, package["manifest"]["id"], package)

        database_path = root / "runtime.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}", future=True)
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        registry = load_registry(widgets_dir)
        auth_service = AuthService(session_factory=session_factory)
        await auth_service.ensure_default_user()
        settings_service = SystemSettingsService(session_factory=session_factory)
        await settings_service.ensure_defaults(user_id=settings.default_user_id)
        plugin_manager = PluginManagerService(
            session_factory=session_factory,
            widgets_dir=widgets_dir,
            registry=registry,
        )
        await plugin_manager.sync_with_filesystem()
        provider_runtime = ProviderRuntime(settings)
        provider_registry = ExternalProviderRegistry(provider_runtime)
        event_bus = EventBus()
        presence_manager = PresenceManager(
            event_bus=event_bus,
            board_id=settings.default_board_id,
            idle_after_seconds=90,
        )
        agent_registry = AgentRegistry(event_bus=event_bus)
        generation_pipeline = GenerationPipelineService(
            session_factory=session_factory,
            plugin_manager=plugin_manager,
            settings_service=settings_service,
            agent_registry=agent_registry,
        )
        await generation_pipeline.start()
        runtime_manager = RuntimeManager(
            session_factory=session_factory,
            registry=registry,
            event_bus=event_bus,
            board_id=settings.default_board_id,
            is_widget_enabled=plugin_manager.is_enabled,
            presence_manager=presence_manager,
            monitor_interval_seconds=monitor_interval_seconds,
        )
        observability_service = ObservabilityService(
            session_factory=session_factory,
            board_id=settings.default_board_id,
            registry=registry,
            event_bus=event_bus,
            runtime_manager=runtime_manager,
            settings_service=settings_service,
            agent_registry=agent_registry,
            presence_manager=presence_manager,
        )
        runtime_manager.capture_metrics = observability_service.capture_runtime_snapshot
        control_plane = ControlPlaneService(
            session_factory=session_factory,
            registry=registry,
            plugin_manager=plugin_manager,
            runtime_manager=runtime_manager,
            event_bus=event_bus,
            presence_manager=presence_manager,
            generation_pipeline=generation_pipeline,
            agent_registry=agent_registry,
        )
        await observability_service.start_event_sink()

        app = FastAPI()

        async def override_get_session():
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        app.state.registry = registry
        app.state.provider_registry = provider_registry
        app.state.plugin_manager = plugin_manager
        app.state.event_bus = event_bus
        app.state.presence_manager = presence_manager
        app.state.agent_registry = agent_registry
        app.state.runtime_manager = runtime_manager
        app.state.auth_service = auth_service
        app.state.system_settings = settings_service
        app.state.observability = observability_service
        app.state.generation_pipeline = generation_pipeline
        app.state.control_plane = control_plane
        app.state.session_factory = session_factory

        @app.middleware("http")
        async def attach_auth_context(request: Request, call_next: Callable[[Request], Any]) -> Response:
            resolution = await auth_service.resolve_context(
                header_user_id=request.headers.get("x-gremlin-user"),
                session_id=request.cookies.get(settings.session_cookie_name)
                or request.headers.get("x-gremlin-session"),
            )
            request.state.auth_context = resolution.context
            response = await call_next(request)
            if resolution.set_cookie_session_id is not None:
                response.set_cookie(
                    settings.session_cookie_name,
                    resolution.set_cookie_session_id,
                    httponly=True,
                    samesite="lax",
                    max_age=settings.session_ttl_hours * 3600,
                )
            return response

        app.include_router(board.router, prefix="/api")
        app.include_router(plugins.router, prefix="/api")
        app.include_router(runtime.router, prefix="/api")
        app.include_router(control.router, prefix="/api")
        app.include_router(devtools.router, prefix="/api")
        app.include_router(agents.router, prefix="/api")
        app.include_router(observability.router, prefix="/api")

        await runtime_manager.bootstrap()

        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
        return cls(
            root=root,
            package_name=package_name,
            widgets_dir=widgets_dir,
            engine=engine,
            session_factory=session_factory,
            registry=registry,
            auth_service=auth_service,
            settings_service=settings_service,
            plugin_manager=plugin_manager,
            provider_runtime=provider_runtime,
            provider_registry=provider_registry,
            event_bus=event_bus,
            presence_manager=presence_manager,
            agent_registry=agent_registry,
            generation_pipeline=generation_pipeline,
            control_plane=control_plane,
            runtime_manager=runtime_manager,
            observability=observability_service,
            app=app,
            client=client,
        )

    async def close(self) -> None:
        try:
            await self.client.aclose()
        finally:
            await self.generation_pipeline.shutdown()
            await self.runtime_manager.shutdown()
            await self.observability.shutdown_event_sink()
            await self.provider_runtime.close()
            await self.engine.dispose()
            if str(self.root.resolve()) in sys.path:
                sys.path.remove(str(self.root.resolve()))
            _purge_test_modules(self.package_name)
            if self.root.exists():
                shutil.rmtree(self.root)

    async def widget(self, widget_instance_id: str) -> WidgetInstanceRead | None:
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            record = await repository.get_widget(widget_instance_id)
            return serialize_widget(record) if record is not None else None

    async def logs(self, *, widget_id: str | None = None) -> list[RuntimeLogRead]:
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            records = await repository.list_runtime_logs(limit=200)
            serialized = [serialize_runtime_log(record) for record in records]
        if widget_id is None:
            return serialized
        return [record for record in serialized if record.widget_id == widget_id]

    async def metrics(self) -> list[RuntimeMetricRead]:
        async with self.session_factory() as session:
            repository = PlatformRepository(session)
            return [serialize_metric(record) for record in await repository.list_metrics(limit=200)]

    async def wait_for_widget(
        self,
        widget_instance_id: str,
        *,
        predicate: Callable[[WidgetInstanceRead], bool],
        timeout: float = 5.0,
        interval: float = 0.05,
    ) -> WidgetInstanceRead:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            widget = await self.widget(widget_instance_id)
            if widget is not None and predicate(widget):
                return widget
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError(f"timed out waiting for widget {widget_instance_id}")
            await asyncio.sleep(interval)

    async def wait_for_log(
        self,
        *,
        predicate: Callable[[RuntimeLogRead], bool],
        timeout: float = 5.0,
        interval: float = 0.05,
    ) -> RuntimeLogRead:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            for record in await self.logs():
                if predicate(record):
                    return record
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError("timed out waiting for runtime log")
            await asyncio.sleep(interval)


def _purge_test_modules(package_name: str) -> None:
    for module_name in list(sys.modules):
        if module_name == package_name or module_name.startswith(f"{package_name}."):
            sys.modules.pop(module_name, None)
