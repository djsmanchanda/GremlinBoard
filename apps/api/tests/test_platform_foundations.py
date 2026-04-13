import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gremlinboard_api.config import settings
from gremlinboard_api.db import Base
from gremlinboard_api.registry.loader import load_registry
from gremlinboard_api.repositories.board import BoardRepository
from gremlinboard_api.runtime.events import EventBus
from gremlinboard_api.runtime.manager import RuntimeManager
from gremlinboard_api.schemas.contracts import (
    ApiCredentialUpsertRequest,
    LifecycleState,
    SystemSettingsUpdateRequest,
    TileSize,
)
from gremlinboard_api.services.auth import AuthService
from gremlinboard_api.services.observability import ObservabilityService
from gremlinboard_api.services.system_settings import SystemSettingsService


@pytest.mark.asyncio
async def test_system_settings_and_auth_foundation_round_trip() -> None:
    root = Path("data") / f"platform-settings-{uuid4().hex}"
    database_path = root / "platform.db"
    root.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    auth_service = AuthService(session_factory=session_factory)
    system_settings = SystemSettingsService(session_factory=session_factory)

    await auth_service.ensure_default_user()
    await system_settings.ensure_defaults(user_id=settings.default_user_id)

    context = await auth_service.resolve_context(header_user_id=None, session_id=None)
    assert context.context.user.id == settings.default_user_id
    assert context.set_cookie_session_id is not None

    updated = await system_settings.update(
        SystemSettingsUpdateRequest(
            runtime={"monitor_interval_seconds": 7, "metrics_retention_points": 140, "log_view_limit": 160},
            ai={
                "default_provider_id": "claude",
                "fallback_provider_ids": ["codex"],
                "enabled_provider_ids": ["codex", "claude"],
            },
        ),
        user_id=settings.default_user_id,
    )
    assert updated.runtime.monitor_interval_seconds == 7
    assert updated.ai.default_provider_id == "claude"

    credential = await system_settings.upsert_credential(
        payload=ApiCredentialUpsertRequest(provider="openai", label="Primary", value="super-secret-key"),
        credential_id=None,
        user_id=settings.default_user_id,
    )
    assert credential.masked_value.startswith("sup")
    assert len(await system_settings.list_credentials()) == 1

    await engine.dispose()
    if root.exists():
        shutil.rmtree(root)


@pytest.mark.asyncio
async def test_observability_snapshot_builds_health_overview() -> None:
    root = Path("data") / f"platform-observability-{uuid4().hex}"
    database_path = root / "platform.db"
    root.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    auth_service = AuthService(session_factory=session_factory)
    await auth_service.ensure_default_user()
    system_settings = SystemSettingsService(session_factory=session_factory)
    await system_settings.ensure_defaults(user_id=settings.default_user_id)

    registry = load_registry(settings.widgets_dir)
    event_bus = EventBus()
    runtime_manager = RuntimeManager(
        session_factory=session_factory,
        registry=registry,
        event_bus=event_bus,
        board_id=settings.default_board_id,
    )
    observability = ObservabilityService(
        session_factory=session_factory,
        board_id=settings.default_board_id,
        registry=registry,
        event_bus=event_bus,
        runtime_manager=runtime_manager,
        settings_service=system_settings,
    )

    async with session_factory() as session:
        board_repository = BoardRepository(session)
        await board_repository.ensure_board(
            settings.default_board_id,
            "GremlinBoard",
            owner_user_id=settings.default_user_id,
        )
        widget = await board_repository.create_widget(
            board_id=settings.default_board_id,
            owner_user_id=settings.default_user_id,
            widget_id="countdown",
            title="Health Check",
            size=TileSize.TALL,
            position_index=0,
            config={"label": "Health"},
            lifecycle_state=LifecycleState.RUNNING,
            expires_at=None,
        )
        await board_repository.create_runtime_log(
            widget_instance_id=widget.id,
            widget_id=widget.widget_id,
            level="info",
            event="runtime.seeded",
            message="runtime seeded",
            context={},
        )

    await observability.capture_runtime_snapshot()
    overview = await observability.overview(limit=20)

    assert overview.summary["widgets_total"] == 1
    assert overview.widget_health[0].widget_id == "countdown"
    assert any(metric.metric_name == "widgets_total" for metric in overview.metrics)
    assert overview.timeline[0].event == "runtime.seeded"

    await engine.dispose()
    if root.exists():
        shutil.rmtree(root)
