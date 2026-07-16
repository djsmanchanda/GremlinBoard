import asyncio
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gremlinboard_api.config import settings
from gremlinboard_api.db import Base
from gremlinboard_api.ai.providers import ClaudeProvider, CodexProvider
from gremlinboard_api.registry.loader import load_registry
from gremlinboard_api.repositories.board import BoardRepository
from gremlinboard_api.repositories.generation import GenerationRepository
from gremlinboard_api.schemas.contracts import (
    AgentEntityType,
    AgentStatus,
    ApiCredentialUpsertRequest,
    EasyGenerationCreateRequest,
    GenerationJobCreateRequest,
    GenerationJobFeedbackRequest,
    GenerationJobStatus,
    WidgetSpecDraft,
)
from gremlinboard_api.services.agent_registry import AgentRegistry
from gremlinboard_api.services.auth import AuthService
from gremlinboard_api.services.event_bus import EventBus
from gremlinboard_api.services.generation_pipeline import GenerationPipelineService
from gremlinboard_api.services.plugin_manager import PluginManagerService
from gremlinboard_api.services.system_settings import SystemSettingsService
from gremlinboard_api.specs.pipeline import scaffold_preview


class _FakeLiveClient:
    """Minimal live-client double that mimics AnthropicClient/OpenAIClient usage reporting."""

    def __init__(
        self,
        *,
        json_responses: list[dict[str, Any]],
        text_responses: list[str],
        usage_sequence: list[dict[str, Any]],
    ) -> None:
        self.json_responses = list(json_responses)
        self.text_responses = list(text_responses)
        self.usage_sequence = list(usage_sequence)
        self.on_usage = None

    async def complete_json(self, **_kwargs: Any) -> dict[str, Any]:
        self._report_usage()
        return self.json_responses.pop(0)

    async def complete_text(self, **_kwargs: Any) -> str:
        self._report_usage()
        return self.text_responses.pop(0)

    def _report_usage(self) -> None:
        if self.usage_sequence and self.on_usage is not None:
            self.on_usage(self.usage_sequence.pop(0))


class _GatedDraftProvider(CodexProvider):
    """Delegates to the real (offline) draft_spec, but only after `gate` is set.

    Lets tests prove that spec drafting for idea-based jobs runs in the worker (not
    the request path) by holding the worker at the draft_spec call until the test
    releases it.
    """

    def __init__(self, *, gate: asyncio.Event) -> None:
        super().__init__()
        self._gate = gate
        self.draft_calls = 0

    async def draft_spec(self, *, idea: str, model_id: str | None = None, reasoning_effort: str | None = "medium") -> dict[str, Any]:
        self.draft_calls += 1
        await self._gate.wait()
        return await super().draft_spec(idea=idea, model_id=model_id, reasoning_effort=reasoning_effort)


class _CustomIdDraftProvider(CodexProvider):
    """Returns a widget spec whose id differs from the deterministic provisional id.

    Used to prove the worker re-stamps the job's widget id from the drafted spec,
    rather than keeping whatever provisional id was assigned at job-creation time.
    """

    def __init__(self, *, gate: asyncio.Event, widget_id: str) -> None:
        super().__init__()
        self._gate = gate
        self._widget_id = widget_id

    async def draft_spec(self, *, idea: str, model_id: str | None = None, reasoning_effort: str | None = "medium") -> dict[str, Any]:
        await self._gate.wait()
        return {
            "id": self._widget_id,
            "name": "Forced Widget",
            "category": "custom",
            "description": "Forced widget spec used to exercise widget id re-stamping.",
            "min_size": "2x2",
            "preferred_size": "4x2",
            "refresh_policy": {"mode": "interval", "interval_seconds": 300},
            "source_type": "generated",
            "permissions": ["network"],
            "output_schema": {"summary": "string"},
            "renderer_type": "card",
            "lifecycle_policy": {"expires": False, "stateful": True},
        }


class _FailingDraftProvider(CodexProvider):
    """Always raises from draft_spec, to exercise the worker's failure path."""

    async def draft_spec(self, *, idea: str, model_id: str | None = None, reasoning_effort: str | None = "medium") -> dict[str, Any]:
        raise RuntimeError("boom - spec drafting exploded")


_FAKE_BACKEND_SOURCE = """
from __future__ import annotations

from gremlinboard_api.runtime.base import BaseWidgetService


class OpsStatusService(BaseWidgetService):
    async def start(self) -> None:
        self.state = await self.get_state()

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        return {"status": "running", "provider": "fake-live", "refresh_mode": "interval"}

    async def get_state(self) -> dict[str, object]:
        return {
            "kind": "ops_status",
            "title": "Ops Status",
            "category": "custom",
            "description": "Operational status snapshot",
            "output": {"summary": "ok", "status": "green"},
        }
"""


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


class _CapturingClient:
    """Live-client double that records every complete_json/complete_text call kwargs.

    Used to prove (a) that `submit_feedback` calls `provider.refine_spec` for a
    live/cli-capable provider instead of silently falling through to the offline
    keyword heuristic (the exact bug this packet fixes: `refine_spec` did not exist on
    `AIProvider` at all, so `getattr(provider, "refine_spec", None)` was always `None`
    and no test caught it), and (b) that the regenerated blueprint/backend prompts
    actually receive the raw operator feedback text.
    """

    def __init__(self, *, json_responses: list[dict[str, Any]], text_responses: list[str]) -> None:
        self.json_responses = list(json_responses)
        self.text_responses = list(text_responses)
        self.json_calls: list[dict[str, Any]] = []
        self.text_calls: list[dict[str, Any]] = []
        self.on_usage = None

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        self.json_calls.append(kwargs)
        return self.json_responses.pop(0)

    async def complete_text(self, **kwargs: Any) -> str:
        self.text_calls.append(kwargs)
        return self.text_responses.pop(0)


class _RefineSpyProvider(CodexProvider):
    """Wraps the real `refine_spec` to count invocations without changing behavior."""

    def __init__(self, *, client: Any) -> None:
        super().__init__(client=client)
        self.refine_spec_calls = 0

    async def refine_spec(self, **kwargs: Any) -> dict[str, Any]:
        self.refine_spec_calls += 1
        return await super().refine_spec(**kwargs)


@pytest.mark.asyncio
async def test_submit_feedback_calls_provider_refine_spec_and_threads_feedback_into_regeneration() -> None:
    root = Path("data") / f"feedback-refine-test-{uuid4().hex}"
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
        generation_service = GenerationPipelineService(
            session_factory=session_factory,
            plugin_manager=plugin_manager,
            settings_service=settings_service,
        )

        original_spec = {
            "id": "feedback_target",
            "name": "Feedback Target",
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
        original_blueprint = {
            "blueprint_version": "1",
            "widget_id": "feedback_target",
            "layouts": {"medium": {"type": "text", "literal": "Ops", "variant": "title"}},
        }

        async with session_factory() as session:
            repository = GenerationRepository(session)
            source_job = await repository.create_job(
                widget_id="feedback_target",
                provider_id="codex",
                requested_provider_id="codex",
                stage_id=None,
                idea=None,
                artifact_version=1,
                selected_version="0.1.0",
                status=GenerationJobStatus.COMPLETED,
                current_step="completed",
                progress=100,
                install_blocked=True,
            )
            await repository.add_artifact(
                job_id=source_job.id,
                widget_id=source_job.widget_id,
                artifact_version=source_job.artifact_version,
                stage="spec",
                artifact_type="normalized_spec",
                payload={"spec": original_spec},
            )
            await repository.add_artifact(
                job_id=source_job.id,
                widget_id=source_job.widget_id,
                artifact_version=source_job.artifact_version,
                stage="codegen",
                artifact_type="package",
                payload={"package": {"blueprint": original_blueprint}},
            )

        feedback_text = "add a refresh button, marker XYZ777"
        refined_spec_payload = dict(original_spec) | {"name": "Feedback Target Refreshed"}

        capturing_client = _CapturingClient(
            json_responses=[
                refined_spec_payload,  # refine_spec (submit_feedback)
                {
                    "blueprint_version": "1",
                    "widget_id": "feedback_target",
                    "layouts": {"medium": {"type": "text", "literal": "Ops", "variant": "title"}},
                },  # generate_blueprint
                {"summary": "ok", "issues": [], "requires_human_review": True},  # review_package
            ],
            text_responses=[_FAKE_BACKEND_SOURCE.replace("OpsStatusService", "FeedbackTargetService")],
        )
        spy_provider = _RefineSpyProvider(client=capturing_client)
        generation_service.providers["codex"] = spy_provider
        await generation_service.start()

        feedback = await generation_service.submit_feedback(
            job_id=source_job.id,
            payload=GenerationJobFeedbackRequest(feedback=feedback_text, provider_id="codex"),
        )

        # (a) The bug this packet fixes: refine_spec must actually be invoked, not
        # silently skipped in favor of the offline keyword heuristic.
        assert spy_provider.refine_spec_calls == 1
        assert feedback.metadata["refinement"]["source"] == "provider"
        assert feedback.metadata["refinement"]["generation_mode"] == "live"
        assert feedback.metadata["refined_spec"]["name"] == "Feedback Target Refreshed"
        assert capturing_client.json_calls[0]["user_prompt"].count(feedback_text) >= 1

        refined_job = await wait_for_generation(generation_service, feedback.job.id)
        assert refined_job.status == "completed"

        # (b) The blueprint/backend regeneration for this same job must see the raw
        # feedback text, not just the (possibly barely-changed) refined spec.
        blueprint_call = capturing_client.json_calls[1]
        review_call = capturing_client.json_calls[2]
        backend_call = capturing_client.text_calls[0]
        assert feedback_text in blueprint_call["user_prompt"]
        assert feedback_text in backend_call["user_prompt"]
        # Review does not need the raw feedback text per the spec.
        assert feedback_text not in review_call["user_prompt"]

        await generation_service.shutdown()
    finally:
        await engine.dispose()
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)


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
        assert job.token_usage is None

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
async def test_generation_pipeline_live_run_persists_aggregated_token_usage() -> None:
    root = Path("data") / f"generation-live-usage-test-{uuid4().hex}"
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
        await settings_service.upsert_credential(
            ApiCredentialUpsertRequest(provider="codex", label="fake codex key", value="fake-key"),
            credential_id=None,
            user_id=settings.default_user_id,
        )
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

        fake_client = _FakeLiveClient(
            json_responses=[
                {
                    "blueprint_version": "1",
                    "widget_id": "ops_status",
                    "layouts": {"medium": {"type": "text", "literal": "Ops", "variant": "title"}},
                },
                {"summary": "Looks solid.", "issues": [], "checklist": [], "requires_human_review": True},
            ],
            text_responses=[_FAKE_BACKEND_SOURCE],
            usage_sequence=[
                {"input_tokens": 400, "output_tokens": 150, "model": "gpt-5.5"},
                {"input_tokens": 300, "output_tokens": 900, "model": "gpt-5.5"},
                {"input_tokens": 120, "output_tokens": 60, "model": "gpt-5.5"},
            ],
        )
        generation_service.providers["codex"] = CodexProvider(client=fake_client)

        await generation_service.start()

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
        job = await wait_for_generation(generation_service, queued.id)

        assert job.status == "completed"
        assert job.token_usage is not None
        assert job.token_usage.input_tokens == 400 + 300 + 120
        assert job.token_usage.output_tokens == 150 + 900 + 60
        assert job.token_usage.calls == 3

        codegen_artifact = next(
            artifact
            for artifact in job.artifacts
            if artifact.stage == "codegen" and artifact.artifact_type == "package"
        )
        assert codegen_artifact.payload is not None
        codegen_usage = codegen_artifact.payload["usage"]
        assert codegen_usage["input_tokens"] == 400 + 300
        assert codegen_usage["output_tokens"] == 150 + 900

        review_artifact = next(
            artifact for artifact in job.artifacts if artifact.stage == "review" and artifact.artifact_type == "report"
        )
        assert review_artifact.payload is not None
        review_usage = review_artifact.payload["usage"]
        assert review_usage["input_tokens"] == 120
        assert review_usage["output_tokens"] == 60

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
async def test_generation_pipeline_requeues_persisted_job_after_restart() -> None:
    root = Path("data") / f"generation-restart-test-{uuid4().hex}"
    database_path = root / "generation.db"
    widgets_dir = root / "widgets"
    root.mkdir(parents=True, exist_ok=True)
    widgets_dir.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}", future=True)
    first_service: GenerationPipelineService | None = None
    restarted_service: GenerationPipelineService | None = None
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
        spec = WidgetSpecDraft.model_validate(
            {
                "id": "restartable_ops_status",
                "name": "Restartable Ops Status",
                "category": "custom",
                "description": "Operational status snapshot that survives a worker restart",
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

        first_service = GenerationPipelineService(
            session_factory=session_factory,
            plugin_manager=plugin_manager,
            settings_service=settings_service,
        )
        # Simulate a process ending after the job is persisted but before a worker is started.
        first_service._queue = asyncio.Queue()
        first_service._ensure_worker_started = AsyncMock()
        queued = await first_service.create_job(
            GenerationJobCreateRequest(stage_id=stage.id, provider_id="codex")
        )
        assert queued.status == "queued"
        assert first_service.queue_status()["queue_depth"] == 1
        await first_service.shutdown()

        restarted_service = GenerationPipelineService(
            session_factory=session_factory,
            plugin_manager=plugin_manager,
            settings_service=settings_service,
        )
        processed_job_ids: list[str] = []

        async def complete_requeued_job(job_id: str) -> None:
            processed_job_ids.append(job_id)
            async with session_factory() as session:
                repository = GenerationRepository(session)
                record = await repository.get_job(job_id)
                assert record is not None
                await repository.update_job(record, status=GenerationJobStatus.RUNNING, current_step="spec", progress=10)
                await repository.update_job(
                    record,
                    status=GenerationJobStatus.COMPLETED,
                    current_step="completed",
                    progress=100,
                    install_blocked=True,
                )

        restarted_service._queue = asyncio.Queue()
        await restarted_service._recover_interrupted_jobs_locked()
        recovered_job_id = await restarted_service._queue.get()
        await complete_requeued_job(recovered_job_id)
        completed = await wait_for_generation(restarted_service, queued.id)

        assert recovered_job_id == queued.id
        assert processed_job_ids == [queued.id]
        assert completed.status == "completed"
        assert completed.install_blocked is True
        assert any(log.message == "Generation job re-queued after worker restart." for log in completed.logs)
    finally:
        if restarted_service is not None:
            await restarted_service.shutdown()
        if first_service is not None:
            await first_service.shutdown()
        await engine.dispose()
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)


@pytest.mark.asyncio
async def test_generation_pipeline_critical_review_issue_blocks_approval() -> None:
    root = Path("data") / f"generation-critical-review-test-{uuid4().hex}"
    database_path = root / "generation.db"
    widgets_dir = root / "widgets"
    root.mkdir(parents=True, exist_ok=True)
    widgets_dir.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}", future=True)
    generation_service: GenerationPipelineService | None = None
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
        async with session_factory() as session:
            repository = GenerationRepository(session)
            completed = await repository.create_job(
                widget_id="critical_review_widget",
                provider_id="codex",
                requested_provider_id="codex",
                stage_id=None,
                idea="Critical review gate regression fixture.",
                artifact_version=1,
                selected_version="0.1.0",
                status=GenerationJobStatus.COMPLETED,
                current_step="completed",
                progress=100,
                install_blocked=True,
            )
            await repository.add_artifact(
                job_id=completed.id,
                widget_id=completed.widget_id,
                artifact_version=completed.artifact_version,
                stage="review",
                artifact_type="report",
                payload={
                    "issues": [
                        {
                            "severity": "critical",
                            "area": "backend",
                            "message": "Backend capability review rejected the generated package.",
                        }
                    ],
                    "dry_run": {"ok": True},
                },
            )
        generation_service = GenerationPipelineService(
            session_factory=session_factory,
            plugin_manager=plugin_manager,
            settings_service=settings_service,
        )

        with pytest.raises(ValueError, match="Backend capability review rejected"):
            await generation_service.approve_job(job_id=completed.id)

        blocked = await generation_service.get_job(job_id=completed.id)
        assert blocked.status == "completed"
        assert blocked.install_blocked is True
    finally:
        if generation_service is not None:
            await generation_service.shutdown()
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


@pytest.mark.asyncio
async def test_easy_generation_create_returns_before_spec_drafting_completes() -> None:
    root = Path("data") / f"easy-generation-async-{uuid4().hex}"
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
        gate = asyncio.Event()
        provider = _GatedDraftProvider(gate=gate)
        generation_service.providers["codex"] = provider
        await generation_service.start()

        # If draft_spec ran inline in the request path this would hang until the gate
        # is set; the timeout proves create_easy_job returns without waiting on it.
        easy = await asyncio.wait_for(
            generation_service.create_easy_job(
                EasyGenerationCreateRequest(
                    idea="Build a compact ops status widget with a health summary.",
                    provider_id="codex",
                )
            ),
            timeout=2.0,
        )
        assert easy.job.status == "queued"
        assert easy.test_box is None
        assert easy.job.widget_id

        # Let the worker reach (and block on) the gated draft_spec call.
        deadline = asyncio.get_running_loop().time() + 2.0
        while provider.draft_calls == 0:
            assert asyncio.get_running_loop().time() < deadline, "worker never reached draft_spec"
            await asyncio.sleep(0.02)

        still_queued = await generation_service.get_job(job_id=easy.job.id)
        assert still_queued.status in {"queued", "running"}
        assert still_queued.status != "completed"

        gate.set()
        job = await wait_for_generation(generation_service, easy.job.id)
        assert job.status == "completed"

        await generation_service.shutdown()
    finally:
        await engine.dispose()
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)


@pytest.mark.asyncio
async def test_idea_job_widget_id_is_provisional_then_restamped_after_drafting() -> None:
    root = Path("data") / f"idea-restamp-test-{uuid4().hex}"
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
        generation_service = GenerationPipelineService(
            session_factory=session_factory,
            plugin_manager=plugin_manager,
            settings_service=settings_service,
        )
        gate = asyncio.Event()
        forced_widget_id = "totally_different_widget"
        generation_service.providers["codex"] = _CustomIdDraftProvider(gate=gate, widget_id=forced_widget_id)
        await generation_service.start()

        queued = await generation_service.create_job(
            GenerationJobCreateRequest(
                idea='Build a "Sprint Risk" dashboard widget with alerts.',
                provider_id="codex",
            )
        )
        assert queued.status == "queued"
        assert queued.stage_id is None
        provisional_widget_id = queued.widget_id
        assert provisional_widget_id
        assert provisional_widget_id != forced_widget_id

        gate.set()
        job = await wait_for_generation(generation_service, queued.id)

        assert job.status == "completed"
        assert job.widget_id == forced_widget_id
        assert job.stage_id is not None
        assert job.install_target is not None
        assert job.install_target["widget_id"] == forced_widget_id

        await generation_service.shutdown()
    finally:
        await engine.dispose()
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)


@pytest.mark.asyncio
async def test_idea_job_draft_spec_failure_fails_job_with_error_message() -> None:
    root = Path("data") / f"idea-draft-failure-test-{uuid4().hex}"
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
        generation_service = GenerationPipelineService(
            session_factory=session_factory,
            plugin_manager=plugin_manager,
            settings_service=settings_service,
        )
        generation_service.providers["codex"] = _FailingDraftProvider()
        await generation_service.start()

        queued = await generation_service.create_job(
            GenerationJobCreateRequest(
                idea="Build a widget whose drafting will fail.",
                provider_id="codex",
            )
        )
        assert queued.status == "queued"

        job = await wait_for_generation(generation_service, queued.id)
        assert job.status == "failed"
        assert job.error_message is not None
        assert "boom" in job.error_message

        await generation_service.shutdown()
    finally:
        await engine.dispose()
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)


@pytest.mark.asyncio
async def test_generation_pipeline_requeues_persisted_idea_job_and_drafts_after_restart() -> None:
    root = Path("data") / f"idea-restart-test-{uuid4().hex}"
    database_path = root / "generation.db"
    widgets_dir = root / "widgets"
    root.mkdir(parents=True, exist_ok=True)
    widgets_dir.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}", future=True)
    first_service: GenerationPipelineService | None = None
    restarted_service: GenerationPipelineService | None = None
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

        first_service = GenerationPipelineService(
            session_factory=session_factory,
            plugin_manager=plugin_manager,
            settings_service=settings_service,
        )
        # Simulate a process ending after the job is persisted but before a worker is started.
        first_service._queue = asyncio.Queue()
        first_service._ensure_worker_started = AsyncMock()
        queued = await first_service.create_job(
            GenerationJobCreateRequest(
                idea="Build a compact restart ops widget with a status summary.",
                provider_id="codex",
            )
        )
        assert queued.status == "queued"
        assert queued.stage_id is None
        provisional_widget_id = queued.widget_id
        assert first_service.queue_status()["queue_depth"] == 1
        await first_service.shutdown()

        restarted_service = GenerationPipelineService(
            session_factory=session_factory,
            plugin_manager=plugin_manager,
            settings_service=settings_service,
        )
        # Re-derive the queued input straight from the persisted payload, mirroring what
        # the worker does on restart: it should carry the raw idea forward with no spec,
        # ready to draft on the next run.
        restarted_service._queue = asyncio.Queue()
        await restarted_service._recover_interrupted_jobs_locked()
        recovered_job_id = await restarted_service._queue.get()
        assert recovered_job_id == queued.id
        queued_input = await restarted_service._load_queued_input(recovered_job_id)
        assert queued_input.spec is None
        assert queued_input.idea is not None

        restarted_service._queue.put_nowait(recovered_job_id)
        restarted_service._ensure_worker_started_locked()
        completed = await wait_for_generation(restarted_service, queued.id)

        assert completed.status == "completed"
        assert completed.widget_id == provisional_widget_id
        assert completed.stage_id is not None
    finally:
        if restarted_service is not None:
            await restarted_service.shutdown()
        if first_service is not None:
            await first_service.shutdown()
        await engine.dispose()
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
