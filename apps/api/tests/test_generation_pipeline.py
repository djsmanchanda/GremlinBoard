import asyncio
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gremlinboard_api.config import settings
from gremlinboard_api.db import Base
from gremlinboard_api.ai.providers import ClaudeProvider, CodexProvider
from gremlinboard_api.registry.loader import load_registry
from gremlinboard_api.repositories.board import BoardRepository
from gremlinboard_api.schemas.contracts import (
    AgentEntityType,
    AgentStatus,
    EasyGenerationCreateRequest,
    GenerationJobCreateRequest,
    GenerationJobFeedbackRequest,
    WidgetSpecDraft,
)
from gremlinboard_api.services.agent_registry import AgentRegistry
from gremlinboard_api.services.auth import AuthService
from gremlinboard_api.services.event_bus import EventBus
from gremlinboard_api.services.generation_pipeline import GenerationPipelineService
from gremlinboard_api.services.plugin_manager import PluginManagerService
from gremlinboard_api.services.system_settings import SystemSettingsService
from gremlinboard_api.specs.pipeline import scaffold_preview


async def wait_for_generation(
    generation_service: GenerationPipelineService,
    job_id: str,
    *,
    timeout_seconds: float = 5,
):
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        job = await generation_service.get_job(job_id=job_id)
        if job.status in {"completed", "failed"}:
            return job
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"generation job {job_id} did not complete; last status={job.status}")
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_ai_provider_fallback_catalog_exposes_current_model_metadata() -> None:
    codex_options, codex_source, codex_status = await CodexProvider().list_model_options(credentials={})
    claude_options, claude_source, claude_status = await ClaudeProvider().list_model_options(credentials={})

    assert codex_source == "fallback"
    assert codex_status == "fallback"
    assert codex_options[0]["id"] == "gpt-5.5"
    assert codex_options[0]["reasoning_effort_options"] == ["none", "low", "medium", "high", "xhigh"]

    assert claude_source == "fallback"
    assert claude_status == "fallback"
    assert claude_options[0]["id"] == "claude-fable-5"
    assert {option["speed_level"] for option in claude_options} >= {"moderate", "fast", "fastest"}


@pytest.mark.asyncio
async def test_generation_pipeline_runs_review_gated_install_flow() -> None:
    root = Path("data") / f"generation-test-{uuid4().hex}"
    database_path = root / "generation.db"
    widgets_dir = root / "widgets"
    root.mkdir(parents=True, exist_ok=True)
    widgets_dir.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}", future=True)
    try:
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
        event_bus = EventBus()
        agent_registry = AgentRegistry(event_bus=event_bus)
        generation_service = GenerationPipelineService(
            session_factory=session_factory,
            plugin_manager=plugin_manager,
            settings_service=settings_service,
            agent_registry=agent_registry,
        )
        await generation_service.start()
        worker_task = generation_service._worker_task
        await generation_service.start()
        assert generation_service._worker_task is worker_task

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

        queued = await generation_service.create_job(
            GenerationJobCreateRequest(stage_id=stage.id, provider_id="codex")
        )
        assert queued.status == "queued"
        queued_agents = await agent_registry.list_agents(status=AgentStatus.QUEUED, type=AgentEntityType.TASK)
        assert [agent.id for agent in queued_agents] == [f"generation:{queued.id}"]
        job = await wait_for_generation(generation_service, queued.id)
        assert job.status == "completed"
        assert job.progress == 100
        assert job.error_message is None
        assert any(artifact.stage == "codegen" for artifact in job.artifacts)
        assert any(log.step == "completed" for log in job.logs)
        assert job.install_target is not None
        assert job.install_target["action"] == "install"

        approved = await generation_service.approve_job(job_id=job.id)
        assert approved.status == "review_required"
        assert approved.install_blocked is False
        review_agents = await agent_registry.list_agents(
            status=AgentStatus.WAITING_FOR_REVIEW,
            type=AgentEntityType.TASK,
        )
        assert [agent.id for agent in review_agents] == [f"generation:{job.id}"]

        installed = await generation_service.install_job(job_id=job.id, enabled=True)
        assert installed.status == "installed"
        completed_agents = await agent_registry.list_agents(status=AgentStatus.COMPLETED, type=AgentEntityType.TASK)
        assert f"generation:{job.id}" in {agent.id for agent in completed_agents}
        plugin = await plugin_manager.get_plugin("ops_status")
        assert plugin is not None
        assert plugin.installed is True
        assert (widgets_dir / "ops_status" / "manifest.json").exists()

        await generation_service.shutdown()
    finally:
        await engine.dispose()
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)


@pytest.mark.asyncio
async def test_generation_pipeline_regeneration_increments_version() -> None:
    root = Path("data") / f"regeneration-test-{uuid4().hex}"
    database_path = root / "regeneration.db"
    widgets_dir = root / "widgets"
    root.mkdir(parents=True, exist_ok=True)
    widgets_dir.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}", future=True)
    try:
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
        await generation_service.start()

        first_queued = await generation_service.create_job(
            GenerationJobCreateRequest(
                idea="Build a wide operations widget with a short health summary and refresh details.",
                provider_id="claude",
            )
        )
        first_job = await wait_for_generation(generation_service, first_queued.id)
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

        await generation_service.shutdown()
    finally:
        await engine.dispose()
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)


@pytest.mark.asyncio
async def test_easy_generation_returns_test_box_and_feedback_refinement_metadata() -> None:
    root = Path("data") / f"easy-generation-test-{uuid4().hex}"
    database_path = root / "easy-generation.db"
    widgets_dir = root / "widgets"
    root.mkdir(parents=True, exist_ok=True)
    widgets_dir.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}", future=True)
    try:
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
        await generation_service.start()

        easy = await generation_service.create_easy_job(
            EasyGenerationCreateRequest(
                idea='Build a wide "Sprint Risk" dashboard with alert, trend chart, and blockers every 5 minutes.',
                provider_id="codex",
            )
        )
        assert easy.job.status == "queued"
        assert easy.test_box is None

        job = await wait_for_generation(generation_service, easy.job.id)
        easy_done = await generation_service.get_easy_job(job_id=job.id)
        assert easy_done.job.status == "completed"
        assert easy_done.job.install_blocked is True
        assert easy_done.feedback_categories == ["name", "sizing", "ui", "feature"]
        assert easy_done.test_box is not None
        assert easy_done.test_box.name == "Sprint Risk"
        assert easy_done.test_box.size == "4x2"
        assert easy_done.test_box.install_blocked is True
        assert easy_done.test_box.review_required is True
        assert easy_done.test_box.renderer == {"kind": "blueprint", "blueprint": "view.blueprint.json"}
        assert "query" in easy_done.test_box.config_schema["properties"]
        assert {"alert", "trend"}.issubset(easy_done.test_box.initial_state["output"])

        feedback = await generation_service.submit_feedback(
            job_id=job.id,
            payload=GenerationJobFeedbackRequest(feedback='Rename to "Risk Pulse" and make it compact 1x1.'),
        )
        assert feedback.category == "name"
        assert feedback.metadata["source_job_id"] == job.id
        assert feedback.metadata["refined_spec"]["name"] == "Risk Pulse"
        assert feedback.metadata["refined_spec"]["preferred_size"] == "1x1"
        assert any(
            artifact.stage == "feedback" and artifact.artifact_type == "refinement"
            for artifact in feedback.job.artifacts
        )

        refined = await wait_for_generation(generation_service, feedback.job.id)
        refined_easy = await generation_service.get_easy_job(job_id=refined.id)
        assert refined_easy.test_box is not None
        assert refined_easy.test_box.name == "Risk Pulse"
        assert refined_easy.test_box.size == "1x1"
        assert refined_easy.job.install_blocked is True

        await generation_service.shutdown()
    finally:
        await engine.dispose()
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
