import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gremlinboard_api.config import settings
from gremlinboard_api.db import Base
from gremlinboard_api.registry.loader import load_registry
from gremlinboard_api.repositories.board import BoardRepository
from gremlinboard_api.schemas.contracts import GenerationJobCreateRequest, WidgetSpecDraft
from gremlinboard_api.services.auth import AuthService
from gremlinboard_api.services.generation_pipeline import GenerationPipelineService
from gremlinboard_api.services.plugin_manager import PluginManagerService
from gremlinboard_api.services.system_settings import SystemSettingsService
from gremlinboard_api.specs.pipeline import scaffold_preview


@pytest.mark.asyncio
async def test_generation_pipeline_runs_review_gated_install_flow() -> None:
    root = Path("data") / f"generation-test-{uuid4().hex}"
    database_path = root / "generation.db"
    widgets_dir = root / "widgets"
    root.mkdir(parents=True, exist_ok=True)
    widgets_dir.mkdir(parents=True, exist_ok=True)

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
    generation_service = GenerationPipelineService(
        session_factory=session_factory,
        plugin_manager=plugin_manager,
        settings_service=settings_service,
    )

    spec = WidgetSpecDraft.model_validate(
        {
            "id": "ops_status",
            "name": "Ops Status",
            "category": "custom",
            "description": "Operational status snapshot",
            "min_size": "2x2",
            "preferred_size": "4x2",
            "refresh_policy": {"mode": "interval", "interval_seconds": 300},
            "source_type": "generated",
            "permissions": ["network"],
            "output_schema": {"summary": "string", "status": "string"},
            "renderer_type": "card",
            "lifecycle_policy": {"expires": False, "stateful": True},
        }
    )

    async with session_factory() as session:
        board_repository = BoardRepository(session)
        stage = await board_repository.create_staged_spec(
            widget_id=spec.id,
            stage="validated",
            spec=spec.model_dump(mode="json"),
            scaffold_preview=scaffold_preview(spec),
            notes=[],
        )

    job = await generation_service.create_job(
        GenerationJobCreateRequest(stage_id=stage.id, provider_id="codex")
    )
    assert job.status == "review_required"
    assert any(artifact.stage == "codegen" for artifact in job.artifacts)
    assert job.install_target is not None
    assert job.install_target["action"] == "install"

    approved = await generation_service.approve_job(job_id=job.id)
    assert approved.status == "approved"

    installed = await generation_service.install_job(job_id=job.id, enabled=True)
    assert installed.status == "installed"
    plugin = await plugin_manager.get_plugin("ops_status")
    assert plugin is not None
    assert plugin.installed is True
    assert (widgets_dir / "ops_status" / "manifest.json").exists()

    await engine.dispose()
    if root.exists():
        shutil.rmtree(root)


@pytest.mark.asyncio
async def test_generation_pipeline_regeneration_increments_version() -> None:
    root = Path("data") / f"regeneration-test-{uuid4().hex}"
    database_path = root / "regeneration.db"
    widgets_dir = root / "widgets"
    root.mkdir(parents=True, exist_ok=True)
    widgets_dir.mkdir(parents=True, exist_ok=True)

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
    generation_service = GenerationPipelineService(
        session_factory=session_factory,
        plugin_manager=plugin_manager,
        settings_service=settings_service,
    )

    first_job = await generation_service.create_job(
        GenerationJobCreateRequest(
            idea="Build a wide operations widget with a short health summary and refresh details.",
            provider_id="claude",
        )
    )
    await generation_service.approve_job(job_id=first_job.id)
    await generation_service.install_job(job_id=first_job.id, enabled=True)

    regenerated = await generation_service.create_job(
        GenerationJobCreateRequest(
            regenerate_from_job_id=first_job.id,
            provider_id="codex",
        )
    )

    assert regenerated.selected_version == "0.1.1"
    assert regenerated.artifact_version == 2
    assert regenerated.install_target is not None
    assert regenerated.install_target["action"] == "update"

    await engine.dispose()
    if root.exists():
        shutil.rmtree(root)
