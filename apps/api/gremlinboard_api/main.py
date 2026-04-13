from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from gremlinboard_api.api.routes import ai, board, health, observability, plugins, registry, runtime, specs, system
from gremlinboard_api.config import settings
from gremlinboard_api.db import SessionLocal, init_db
from gremlinboard_api.registry.loader import load_registry
from gremlinboard_api.repositories.board import BoardRepository
from gremlinboard_api.runtime.events import EventBus
from gremlinboard_api.runtime.manager import RuntimeManager
from gremlinboard_api.schemas.contracts import LifecycleState, TileSize
from gremlinboard_api.services.auth import AuthService
from gremlinboard_api.services.generation_pipeline import GenerationPipelineService
from gremlinboard_api.services.observability import ObservabilityService
from gremlinboard_api.services.fixtures import default_countdown_target
from gremlinboard_api.services.plugin_manager import PluginManagerService
from gremlinboard_api.services.system_settings import SystemSettingsService


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
                {"label": "Release window", "target_time": default_countdown_target(120)},
            ),
            ("sports", "Sports Pulse", TileSize.WIDE, {"sport": "ipl"}),
            ("news", "News Radar", TileSize.MEDIUM, {"topic": "openclaw", "sources": ["demo"]}),
            ("trending", "Trend Stack", TileSize.HIGH, {"sources": ["reddit", "x", "hackernews"]}),
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
    await init_db()
    registry_loader = load_registry(settings.widgets_dir)
    auth_service = AuthService(session_factory=SessionLocal)
    await auth_service.ensure_default_user()
    system_settings = SystemSettingsService(session_factory=SessionLocal)
    await system_settings.ensure_defaults(user_id=settings.default_user_id)
    plugin_manager = PluginManagerService(
        session_factory=SessionLocal,
        widgets_dir=settings.widgets_dir,
        registry=registry_loader,
    )
    await plugin_manager.sync_with_filesystem()
    event_bus = EventBus()
    runtime_manager = RuntimeManager(
        session_factory=SessionLocal,
        registry=registry_loader,
        event_bus=event_bus,
        board_id=settings.default_board_id,
        is_widget_enabled=plugin_manager.is_enabled,
        monitor_interval_seconds=(await system_settings.read()).runtime.monitor_interval_seconds,
    )
    observability_service = ObservabilityService(
        session_factory=SessionLocal,
        board_id=settings.default_board_id,
        registry=registry_loader,
        event_bus=event_bus,
        runtime_manager=runtime_manager,
        settings_service=system_settings,
    )
    runtime_manager.capture_metrics = observability_service.capture_runtime_snapshot
    generation_pipeline = GenerationPipelineService(
        session_factory=SessionLocal,
        plugin_manager=plugin_manager,
        settings_service=system_settings,
    )

    app.state.registry = registry_loader
    app.state.plugin_manager = plugin_manager
    app.state.event_bus = event_bus
    app.state.runtime_manager = runtime_manager
    app.state.generation_pipeline = generation_pipeline
    app.state.auth_service = auth_service
    app.state.system_settings = system_settings
    app.state.observability = observability_service
    app.state.session_factory = SessionLocal

    await seed_default_widgets(SessionLocal)
    await runtime_manager.bootstrap()
    await observability_service.capture_runtime_snapshot()
    yield
    await runtime_manager.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def attach_auth_context(request: Request, call_next):
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
app.include_router(observability.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(board.router, prefix="/api")
app.include_router(specs.router, prefix="/api")
app.include_router(system.router, prefix="/api")
