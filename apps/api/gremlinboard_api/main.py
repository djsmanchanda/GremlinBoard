from __future__ import annotations

import logging
import shutil
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from gremlinboard_api.api.routes import agents, ai, board, control, devtools, health, observability, plugins, registry, runtime, specs, system
from gremlinboard_api.config import ROOT_DIR, settings
from gremlinboard_api.db import SessionLocal, init_db
from gremlinboard_api.providers.registry import ExternalProviderRegistry, ProviderRuntime
from gremlinboard_api.registry.loader import load_registry
from gremlinboard_api.repositories.board import BoardRepository
from gremlinboard_api.runtime.base import ServiceContext
from gremlinboard_api.runtime.events import EventBus
from gremlinboard_api.runtime.manager import RuntimeManager
from gremlinboard_api.schemas.contracts import LifecycleState, TileSize
from gremlinboard_api.services.auth import AuthService
from gremlinboard_api.services.agent_registry import AgentRegistry
from gremlinboard_api.services.control_plane import ControlPlaneService
from gremlinboard_api.services.generation_pipeline import GenerationPipelineService
from gremlinboard_api.services.mcp_server import McpServerService
from gremlinboard_api.services.observability import ObservabilityService
from gremlinboard_api.services.fixtures import default_countdown_target
from gremlinboard_api.services.plugin_manager import PluginManagerService
from gremlinboard_api.services.presence import PresenceManager
from gremlinboard_api.services.system_settings import SystemSettingsService


_migration_logger = logging.getLogger("gremlinboard_api.migration")


def _sqlite_path_from_url(database_url: str) -> Path | None:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return None
    return Path(database_url[len(prefix) :])


def _read_widget_plugin_is_core(db_path: Path) -> dict[str, bool] | None:
    """Read {widget_id: is_core} from a gremlinboard.db, or None if unreadable."""

    if not db_path.exists():
        return None
    try:
        connection = sqlite3.connect(str(db_path))
        try:
            cursor = connection.execute("SELECT widget_id, is_core FROM widget_plugins")
            return {row[0]: bool(row[1]) for row in cursor.fetchall()}
        finally:
            connection.close()
    except sqlite3.Error:
        return None


def migrate_legacy_user_data() -> None:
    """Move mutable user state from the repo into the platform data directory.

    Idempotent and never destructive: the legacy database is copied (not
    moved), and widget directories are only relocated once each — a second
    run finds nothing left to migrate. Runs before DB init/registry load so
    the rest of startup only ever sees the new locations.
    """

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.user_widgets_dir.mkdir(parents=True, exist_ok=True)
    # The isolated widget host imports `widgets.<id>.backend` from this root,
    # so keep it a regular package like the repo's widgets/ directory.
    root_marker = settings.user_widgets_dir / "__init__.py"
    if not root_marker.exists():
        root_marker.write_text('"""GremlinBoard user widget packages."""\n', encoding="utf-8")

    dest_db_path = _sqlite_path_from_url(settings.database_url)
    db_copied = False
    if dest_db_path is not None:
        legacy_db_path = ROOT_DIR / "data" / "gremlinboard.db"
        if not dest_db_path.exists() and legacy_db_path.exists():
            dest_db_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_db_path, dest_db_path)
            db_copied = True

    moved_widgets: list[str] = []
    skipped_widgets: list[str] = []
    is_core_by_widget_id = _read_widget_plugin_is_core(dest_db_path) if dest_db_path is not None else None
    if is_core_by_widget_id is not None and settings.widgets_dir.exists():
        for entry in sorted(settings.widgets_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("__"):
                continue
            widget_id = entry.name
            is_core = is_core_by_widget_id.get(widget_id)
            if is_core is None or is_core:
                if is_core is None:
                    skipped_widgets.append(widget_id)
                continue
            destination = settings.user_widgets_dir / widget_id
            if destination.exists():
                skipped_widgets.append(widget_id)
                continue
            shutil.move(str(entry), str(destination))
            moved_widgets.append(widget_id)

    if db_copied or moved_widgets or skipped_widgets:
        _migration_logger.info(
            "gremlinboard user-data migration: db_copied=%s moved_widgets=%s skipped_widgets=%s -> %s",
            db_copied,
            moved_widgets,
            skipped_widgets,
            settings.data_dir,
        )


async def seed_default_widgets(session_factory) -> None:
    async with session_factory() as session:
        repository = BoardRepository(session)
        await repository.ensure_board(
            settings.default_board_id,
            "GremlinBoard",
            owner_user_id=settings.default_user_id,
        )
        widgets = await repository.list_widgets(settings.default_board_id)
        if widgets:
            return

        defaults = [
            (
                "countdown",
                "Launch Countdown",
                TileSize.TALL,
                {
                    "timers": [
                        {
                            "id": "release-window",
                            "label": "Release window",
                            "target_time": default_countdown_target(120),
                            "duration_seconds": 120 * 60,
                        }
                    ]
                },
            ),
            (
                "sports",
                "Sports Pulse",
                TileSize.WIDE,
                {
                    "sport": "ipl",
                    "provider": "auto",
                    "refresh_behavior": "auto",
                    "refresh_interval_seconds": 120,
                    "cache_ttl_seconds": 90,
                    "competition_code": "PL",
                    "tournament": "IPL",
                },
            ),
            (
                "news",
                "News Radar",
                TileSize.MEDIUM,
                {
                    "provider": "rss",
                    "topic": "openclaw",
                    "feed_urls": [
                        "https://news.ycombinator.com/rss",
                        "https://www.theverge.com/rss/index.xml",
                    ],
                    "refresh_behavior": "interval",
                    "refresh_interval_seconds": 600,
                    "cache_ttl_seconds": 300,
                    "limit": 5,
                    "language": "en",
                },
            ),
            (
                "trending",
                "Trend Stack",
                TileSize.HIGH,
                {
                    "sources": ["reddit", "x", "hackernews"],
                    "subreddit": "technology",
                    "reddit_listing": "hot",
                    "x_query": "technology OR ai",
                    "hn_story_type": "top",
                    "refresh_behavior": "interval",
                    "refresh_interval_seconds": 300,
                    "cache_ttl_seconds": 120,
                    "limit": 5,
                },
            ),
            (
                "pinboard",
                "Ops Pinboard",
                TileSize.HIGH,
                {
                    "notes": [
                        {"id": "1", "text": "Check board runtime health before standup"},
                        {"id": "2", "text": "Review sports provider adapter after MVP cut"},
                    ]
                },
            ),
        ]

        for index, (widget_id, title, size, config) in enumerate(defaults):
            await repository.create_widget(
                board_id=settings.default_board_id,
                owner_user_id=settings.default_user_id,
                widget_id=widget_id,
                title=title,
                size=size,
                position_index=index,
                config=config,
                lifecycle_state=LifecycleState.CREATED,
                expires_at=None,
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate_legacy_user_data()
    await init_db()
    registry_loader = load_registry(settings.widgets_dir, settings.user_widgets_dir)
    provider_runtime = ProviderRuntime(settings)
    provider_registry = ExternalProviderRegistry(provider_runtime)
    auth_service = AuthService(session_factory=SessionLocal)
    await auth_service.ensure_default_user()
    system_settings = SystemSettingsService(session_factory=SessionLocal)
    await system_settings.ensure_defaults(user_id=settings.default_user_id)
    await provider_runtime.secrets.sync_from_repository(SessionLocal)
    plugin_manager = PluginManagerService(
        session_factory=SessionLocal,
        widgets_dir=settings.user_widgets_dir,
        registry=registry_loader,
    )
    await plugin_manager.sync_with_filesystem()
    event_bus = EventBus()
    presence_manager = PresenceManager(
        event_bus=event_bus,
        board_id=settings.default_board_id,
        idle_after_seconds=90,
    )
    agent_registry = AgentRegistry(event_bus=event_bus)
    runtime_manager = RuntimeManager(
        session_factory=SessionLocal,
        registry=registry_loader,
        event_bus=event_bus,
        board_id=settings.default_board_id,
        is_widget_enabled=plugin_manager.is_enabled,
        service_context=ServiceContext(provider_registry=provider_registry),
        presence_manager=presence_manager,
        monitor_interval_seconds=(await system_settings.read()).runtime.monitor_interval_seconds,
    )
    observability_service = ObservabilityService(
        session_factory=SessionLocal,
        board_id=settings.default_board_id,
        registry=registry_loader,
        event_bus=event_bus,
        runtime_manager=runtime_manager,
        settings_service=system_settings,
        agent_registry=agent_registry,
        presence_manager=presence_manager,
    )
    runtime_manager.capture_metrics = observability_service.capture_runtime_snapshot
    generation_pipeline = GenerationPipelineService(
        session_factory=SessionLocal,
        plugin_manager=plugin_manager,
        settings_service=system_settings,
        agent_registry=agent_registry,
    )
    control_plane = ControlPlaneService(
        session_factory=SessionLocal,
        registry=registry_loader,
        plugin_manager=plugin_manager,
        runtime_manager=runtime_manager,
        event_bus=event_bus,
        presence_manager=presence_manager,
        generation_pipeline=generation_pipeline,
        agent_registry=agent_registry,
    )

    app.state.registry = registry_loader
    app.state.provider_registry = provider_registry
    app.state.plugin_manager = plugin_manager
    app.state.event_bus = event_bus
    app.state.presence_manager = presence_manager
    app.state.agent_registry = agent_registry
    app.state.runtime_manager = runtime_manager
    app.state.generation_pipeline = generation_pipeline
    app.state.control_plane = control_plane
    app.state.auth_service = auth_service
    app.state.system_settings = system_settings
    app.state.observability = observability_service
    app.state.session_factory = SessionLocal
    mcp_server.attach(app)

    async with mcp_server.lifespan():
        await observability_service.start_event_sink()
        await generation_pipeline.start()
        await seed_default_widgets(SessionLocal)
        await runtime_manager.bootstrap()
        await observability_service.capture_runtime_snapshot()
        yield
        await generation_pipeline.shutdown()
        await runtime_manager.shutdown()
        await observability_service.shutdown_event_sink()
        await provider_runtime.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
mcp_server = McpServerService()
app.mount("/mcp", mcp_server.asgi_app())
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def attach_auth_context(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    session_id = request.cookies.get(settings.session_cookie_name) or request.headers.get("x-gremlin-session")
    resolution = await request.app.state.auth_service.resolve_context(
        header_user_id=request.headers.get("x-gremlin-user"),
        session_id=session_id,
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    observability = getattr(request.app.state, "observability", None)
    if observability is not None:
        await observability.log_platform_event(
            level="error",
            event="http.unhandled_exception",
            message=str(exc),
            context={"path": str(request.url.path), "method": request.method},
        )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "GremlinBoard hit an unexpected platform error.",
            "path": str(request.url.path),
        },
    )

app.include_router(health.router, prefix="/api")
app.include_router(registry.router, prefix="/api")
app.include_router(plugins.router, prefix="/api")
app.include_router(runtime.router, prefix="/api")
app.include_router(control.router, prefix="/api")
app.include_router(devtools.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(observability.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(board.router, prefix="/api")
app.include_router(specs.router, prefix="/api")
app.include_router(system.router, prefix="/api")
