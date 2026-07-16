from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import unified_diff
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gremlinboard_api.ai.clients import AIClientError
from gremlinboard_api.ai.providers import (
    AIProvider,
    ClaudeProvider,
    CodexProvider,
    _detect_title,
    _slugify,
    provider_from_id,
)
from gremlinboard_api.models.tables import StagedWidgetSpecRecord
from gremlinboard_api.repositories.board import BoardRepository
from gremlinboard_api.repositories.generation import (
    GenerationRepository,
    decode_artifact_payload,
    serialize_job,
)
from gremlinboard_api.schemas.blueprint import collect_binding_paths, validate_blueprint
from gremlinboard_api.schemas.contracts import (
    AIProviderRead,
    EasyGenerationCreateRequest,
    EasyGenerationJobRead,
    GenerationArtifactDiffRead,
    GenerationArtifactFileRead,
    GenerationJobCreateRequest,
    GenerationJobFeedbackRead,
    GenerationJobFeedbackRequest,
    GenerationJobRead,
    GenerationJobStatus,
    GenerationTestBoxRead,
    RuntimeEventPersistence,
    RuntimeEventVisibility,
    GenerationPipelinePreviewRead,
    WidgetPackagePayload,
    WidgetPluginInstallRequest,
    WidgetPluginUpdateRequest,
    WidgetSpecDraft,
)
from gremlinboard_api.services.backend_sandbox import dry_run_backend
from gremlinboard_api.services.plugin_manager import PluginManagerService
from gremlinboard_api.services.scaffold_generator import WidgetScaffoldGenerator
from gremlinboard_api.services.system_settings import SystemSettingsService
from gremlinboard_api.specs.pipeline import (
    build_manifest_preview_with_version,
    scaffold_preview,
    validate_widget_spec,
)

if TYPE_CHECKING:
    from gremlinboard_api.services.agent_registry import AgentRegistry


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueuedGenerationInput:
    job_id: str
    spec: WidgetSpecDraft | None
    provider_id: str
    model_id: str | None
    idea_prompt: str | None
    idea_usage: dict[str, Any] | None = None
    # Raw idea text. Set (with spec left None) when spec drafting is deferred to the worker.
    idea: str | None = None
    # Raw operator feedback text, set only when this job was queued from a feedback
    # refinement (see `submit_feedback`). Threaded into the worker so the blueprint/
    # backend stages regenerate with knowledge of what the operator actually asked for,
    # not just the (possibly barely-changed) refined spec.
    regeneration_hint: str | None = None


@dataclass(frozen=True)
class _ResolvedSpecSource:
    widget_id: str
    spec: WidgetSpecDraft | None
    stage_id: str | None
    idea: str | None = None


class GenerationPipelineService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        plugin_manager: PluginManagerService,
        settings_service: SystemSettingsService,
        agent_registry: "AgentRegistry | None" = None,
        event_bus: Any | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.plugin_manager = plugin_manager
        self.settings_service = settings_service
        self.agent_registry = agent_registry
        self.event_bus = event_bus or getattr(agent_registry, "event_bus", None)
        self.scaffold_generator = WidgetScaffoldGenerator()
        self.providers: dict[str, AIProvider] = {
            "codex": CodexProvider(),
            "claude": ClaudeProvider(),
        }
        self._queue: asyncio.Queue[str] | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._worker_lock = asyncio.Lock()
        self._queued_inputs: dict[str, QueuedGenerationInput] = {}
        self._creation_locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        async with self._worker_lock:
            if self._worker_task is not None and not self._worker_task.done():
                logger.info("generation worker already running")
                return
            if self._queue is None:
                self._queue = asyncio.Queue()
            await self._recover_interrupted_jobs_locked()
            self._ensure_worker_started_locked()
        await self.reconcile_agents()

    async def reconcile_agents(self) -> None:
        if self.agent_registry is None:
            return
        jobs = await self.list_jobs()
        await self.agent_registry.recover_generation_jobs(jobs)

    async def shutdown(self) -> None:
        async with self._worker_lock:
            if self._worker_task is None:
                return
            logger.info("stopping generation worker")
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            finally:
                self._worker_task = None
                logger.info("generation worker stopped")

    async def _ensure_worker_started(self) -> None:
        async with self._worker_lock:
            self._ensure_worker_started_locked()

    def _ensure_worker_started_locked(self) -> None:
        if self._queue is None:
            self._queue = asyncio.Queue()
        if self._worker_task is not None and not self._worker_task.done():
            return
        if self._worker_task is not None:
            logger.warning("generation worker task exited; starting replacement")
        else:
            logger.info("starting generation worker")
        self._worker_task = asyncio.create_task(self._run_worker())

    def queue_status(self) -> dict[str, Any]:
        worker_running = self._worker_task is not None and not self._worker_task.done()
        return {
            "queue_depth": self._queue.qsize() if self._queue is not None else 0,
            "queued_input_count": (self._queue.qsize() if self._queue is not None else 0),
            "worker_running": worker_running,
            "worker_done": self._worker_task.done() if self._worker_task is not None else True,
        }

    async def list_providers(self) -> list[AIProviderRead]:
        settings = await self.settings_service.read()
        credential_secrets = await self.settings_service.list_credential_secrets_by_provider()
        items: list[AIProviderRead] = []
        for provider in self.providers.values():
            health = await provider.health()
            enabled = provider.provider_id in settings.ai.enabled_provider_ids
            model_options, model_catalog_source, model_catalog_status = await provider.list_model_options(
                credentials=credential_secrets,
            )
            model_ids = [str(option["id"]) for option in model_options]
            default_model_id = provider.default_model_id if provider.default_model_id in model_ids else (model_ids[0] if model_ids else None)
            items.append(
                AIProviderRead(
                    provider_id=provider.provider_id,
                    label=provider.label,
                    status="disabled" if not enabled else str(health.get("status", "unknown")),
                    backend=str(health.get("backend")) if health.get("backend") else None,
                    supports_codegen=provider.supports_codegen,
                    supports_review=provider.supports_review,
                    supports_idea_to_spec=provider.supports_idea_to_spec,
                    supported_model_ids=model_ids,
                    default_model_id=default_model_id,
                    model_options=model_options,
                    model_catalog_source=model_catalog_source,
                    model_catalog_status=model_catalog_status,
                )
            )
        return items

    async def preview_generation(self, *, provider_id: str, stage_id: str) -> GenerationPipelinePreviewRead:
        provider = provider_from_id(provider_id, self.providers)
        async with self.session_factory() as session:
            record = await session.get(StagedWidgetSpecRecord, stage_id)
            if record is None:
                raise ValueError(f"unknown spec stage '{stage_id}'")
            spec = json.loads(record.spec_json)
        plan = await provider.build_generation_plan(widget_spec=spec, stage_id=stage_id)
        return GenerationPipelinePreviewRead(
            stage_id=stage_id,
            provider_id=provider.provider_id,
            steps=plan["steps"],
            install_blocked=True,
        )

    async def list_jobs(self, *, widget_id: str | None = None) -> list[GenerationJobRead]:
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            records = await repository.list_jobs(widget_id=widget_id)
            return [await self._serialize_job(session, record.id) for record in records]

    async def get_job(self, *, job_id: str) -> GenerationJobRead:
        async with self.session_factory() as session:
            return await self._serialize_job(session, job_id)

    async def create_job(
        self,
        payload: GenerationJobCreateRequest,
        *,
        regeneration_hint: str | None = None,
    ) -> GenerationJobRead:
        await self._ensure_worker_started()
        provider = await self._select_provider(payload.provider_id, payload.fallback_provider_ids)
        source = await self._resolve_spec_source(payload=payload)
        async with self._creation_lock(source.widget_id):
            artifact_version = await self._next_artifact_version(source.widget_id)
            selected_version = await self._resolve_version(widget_id=source.widget_id, requested_version=payload.version)

            async with self.session_factory() as session:
                repository = GenerationRepository(session)
                job = await repository.create_job_with_log(
                    widget_id=source.widget_id,
                    provider_id=provider.provider_id,
                    requested_provider_id=payload.provider_id,
                    stage_id=source.stage_id,
                    idea=payload.idea,
                    artifact_version=artifact_version,
                    selected_version=selected_version,
                    current_step="queued",
                    progress=0,
                    log_level="info",
                    log_step="queued",
                    log_message="Generation job queued.",
                    log_context={
                        "stage_id": source.stage_id,
                        "provider_id": provider.provider_id,
                        "model_id": payload.model_id,
                        "progress": 0,
                    },
                )
                queued_input = QueuedGenerationInput(
                    job_id=job.id,
                    spec=source.spec,
                    provider_id=provider.provider_id,
                    model_id=payload.model_id,
                    idea_prompt=None,
                    idea_usage=None,
                    idea=source.idea,
                    regeneration_hint=regeneration_hint,
                )
                job.queued_input_json = _serialize_queued_input(queued_input)
                job.model_id = _resolve_provider_model(provider, payload.model_id)
                job.generation_mode = await self._provider_generation_mode(provider)
                await session.commit()

        self._queued_inputs[job.id] = queued_input
        queued_job = await self.get_job(job_id=job.id)
        await self._sync_agent_job(job_id=job.id)
        await self._publish_generation_event(job_id=job.id, stage="queued", progress=0, generation_mode=queued_job.generation_mode)
        await self._queue_job(job.id)
        return queued_job

    async def create_easy_job(self, payload: EasyGenerationCreateRequest) -> EasyGenerationJobRead:
        job = await self.create_job(
            GenerationJobCreateRequest(
                provider_id=payload.provider_id,
                model_id=payload.model_id,
                fallback_provider_ids=payload.fallback_provider_ids,
                idea=payload.idea,
                version=payload.version,
            )
        )
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            await repository.add_log(
                job_id=job.id,
                level="info",
                step="easy_mode",
                message="Easy generation mode queued idea-driven widget generation.",
                context={
                    "mode": "easy",
                    "idea": payload.idea,
                    "feedback_categories": ["name", "sizing", "ui", "feature"],
                },
            )
        return EasyGenerationJobRead(job=job, test_box=_build_test_box_payload(job))

    async def get_easy_job(self, *, job_id: str) -> EasyGenerationJobRead:
        job = await self.get_job(job_id=job_id)
        return EasyGenerationJobRead(job=job, test_box=_build_test_box_payload(job))

    async def submit_feedback(
        self,
        *,
        job_id: str,
        payload: GenerationJobFeedbackRequest,
    ) -> GenerationJobFeedbackRead:
        category = _categorize_feedback(payload.feedback)
        tags: list[str] = [category]
        metadata: dict[str, Any]
        async with self.session_factory() as session:
            generation_repository = GenerationRepository(session)
            source_job = await generation_repository.get_job(job_id)
            if source_job is None:
                raise ValueError(f"unknown generation job '{job_id}'")
            artifact = await generation_repository.get_latest_artifact(
                job_id=job_id,
                stage="spec",
                artifact_type="normalized_spec",
            )
            if artifact is None:
                raise ValueError("feedback requires a previous job with a normalized spec artifact")
            artifact_payload = decode_artifact_payload(artifact)
            previous_spec = WidgetSpecDraft.model_validate(artifact_payload.get("spec"))
            package_artifact = await generation_repository.get_latest_artifact(
                job_id=job_id,
                stage="codegen",
                artifact_type="package",
            )
            current_blueprint = _artifact_blueprint(package_artifact)
            provider = await self._select_provider(payload.provider_id or source_job.provider_id, payload.fallback_provider_ids)
            refined_spec, refinement_details = await self._refine_spec_with_provider(
                provider=provider,
                spec=previous_spec,
                blueprint=current_blueprint,
                feedback=payload.feedback,
                model_id=payload.model_id,
            )
            # Refinement updates the SAME widget in place: pin the id no matter
            # what the model (or heuristic) returned, or a rename would install
            # a duplicate widget instead of an update.
            if refined_spec.id != previous_spec.id:
                refined_spec = refined_spec.model_copy(update={"id": previous_spec.id})
            changed_fields = _changed_spec_fields(previous_spec, refined_spec)
            tags = _derive_feedback_tags(changed_fields=changed_fields, feedback=payload.feedback)
            category = _primary_feedback_category(tags)
            notes = validate_widget_spec(refined_spec)
            if notes:
                raise ValueError("; ".join(notes))

            board_repository = BoardRepository(session)
            stage = await board_repository.create_staged_spec(
                widget_id=refined_spec.id,
                stage="validated",
                spec=refined_spec.model_dump(mode="json"),
                scaffold_preview=scaffold_preview(refined_spec),
                notes=[],
            )
            await generation_repository.add_log(
                job_id=source_job.id,
                level="info",
                step="feedback",
                message="Generation feedback captured for refinement.",
                context={
                    "category": category,
                    "tags": tags,
                    "feedback": payload.feedback,
                    "next_stage_id": stage.id,
                },
            )
            metadata = {
                "source_job_id": source_job.id,
                "source_artifact_version": artifact.artifact_version,
                "refined_stage_id": stage.id,
                "category": category,
                "tags": tags,
                "changed_fields": changed_fields,
                "diff_summary": _format_spec_diff_summary(changed_fields),
                "feedback": payload.feedback,
                "refined_spec": refined_spec.model_dump(mode="json"),
                "refinement": refinement_details,
            }

        queued_job = await self.create_job(
            GenerationJobCreateRequest(
                provider_id=payload.provider_id,
                model_id=payload.model_id,
                fallback_provider_ids=payload.fallback_provider_ids,
                stage_id=stage.id,
            ),
            # Thread the raw feedback text through to the worker so the blueprint/backend
            # regeneration for this same job actually sees what the operator asked for,
            # not just the refined spec (which may only barely differ, e.g. a UI-only ask
            # the spec schema can't fully represent).
            regeneration_hint=payload.feedback,
        )
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            await repository.add_artifact(
                job_id=queued_job.id,
                widget_id=queued_job.widget_id,
                artifact_version=queued_job.artifact_version,
                stage="feedback",
                artifact_type="refinement",
                payload=metadata,
            )
            await repository.add_log(
                job_id=queued_job.id,
                level="info",
                step="feedback",
                message="Generation job queued from feedback refinement.",
                context=metadata,
            )
        refined_job = await self.get_job(job_id=queued_job.id)
        return GenerationJobFeedbackRead(
            category=category,
            tags=tags,
            metadata=metadata,
            job=refined_job,
            test_box=_build_test_box_payload(refined_job),
        )

    async def _queue_job(self, job_id: str) -> None:
        await self._ensure_worker_started()
        if self._queue is None:
            raise RuntimeError("generation queue is not available")
        await self._queue.put(job_id)

    async def _run_worker(self) -> None:
        if self._queue is None:
            return
        queue = self._queue
        logger.info("generation worker running")
        try:
            while True:
                job_id = await queue.get()
                try:
                    logger.info("generation worker picked job %s", job_id)
                    queued_input = self._queued_inputs.pop(job_id, None)
                    if queued_input is None:
                        queued_input = await self._load_queued_input(job_id)
                    provider = provider_from_id(queued_input.provider_id, self.providers)
                    await self._execute_job(
                        job_id=queued_input.job_id,
                        spec=queued_input.spec,
                        provider=provider,
                        model_id=queued_input.model_id,
                        idea=queued_input.idea,
                        idea_prompt=queued_input.idea_prompt,
                        idea_usage=queued_input.idea_usage,
                        regeneration_hint=queued_input.regeneration_hint,
                    )
                    logger.info("generation worker completed job %s", job_id)
                except asyncio.CancelledError:
                    await self._mark_job_failed(
                        job_id=job_id,
                        exc=RuntimeError("generation worker stopped before the job completed"),
                    )
                    raise
                except Exception as exc:
                    logger.exception("generation worker failed job %s", job_id)
                    await self._mark_job_failed(job_id=job_id, exc=exc)
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            logger.info("generation worker cancelled")
            raise

    async def _mark_job_failed(self, *, job_id: str, exc: Exception) -> None:
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            record = await repository.get_job(job_id)
            if record is None:
                return
            if record.status not in {GenerationJobStatus.QUEUED.value, GenerationJobStatus.RUNNING.value}:
                logger.warning("not failing generation job %s from terminal status %s", record.id, record.status)
                return
            await repository.update_job(
                record,
                status=GenerationJobStatus.FAILED,
                current_step="failed",
                error_message=str(exc),
                completed_at=datetime.now(timezone.utc),
            )
            await repository.add_log(
                job_id=record.id,
                level="error",
                step="failed",
                message="Generation job failed.",
                context={"error": str(exc), "progress": record.progress},
            )
        await self._sync_agent_job(job_id=job_id)
        await self._publish_generation_event(job_id=job_id, stage="failed", progress=record.progress, generation_mode=record.generation_mode, level="error", message=str(exc))

    async def _recover_interrupted_jobs_locked(self) -> None:
        if self._queue is None:
            self._queue = asyncio.Queue()
        changed_job_ids: list[str] = []
        requeued_job_ids: list[str] = []
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            queued_records = await repository.list_jobs_by_status({GenerationJobStatus.QUEUED})
            for record in queued_records:
                if not record.queued_input_json:
                    changed_job_ids.append(record.id)
                    await repository.update_job(
                        record,
                        status=GenerationJobStatus.FAILED,
                        current_step="failed",
                        error_message="queued generation input is missing after restart",
                        completed_at=datetime.now(timezone.utc),
                    )
                    await repository.add_log(
                        job_id=record.id,
                        level="error",
                        step="failed",
                        message="Generation job failed after worker restart.",
                        context={"progress": record.progress, "reason": "missing_queued_input"},
                    )
                    continue
                self._queue.put_nowait(record.id)
                requeued_job_ids.append(record.id)
                await repository.add_log(
                    job_id=record.id,
                    level="info",
                    step="queued",
                    message="Generation job re-queued after worker restart.",
                    context={"progress": record.progress},
                )

            running_records = await repository.list_jobs_by_status({GenerationJobStatus.RUNNING})
            for record in running_records:
                changed_job_ids.append(record.id)
                await repository.update_job(
                    record,
                    status=GenerationJobStatus.FAILED,
                    current_step="failed",
                    error_message="generation worker restarted before the job completed",
                    completed_at=datetime.now(timezone.utc),
                )
                await repository.add_log(
                    job_id=record.id,
                    level="error",
                    step="failed",
                    message="Generation job failed after worker restart.",
                    context={"progress": record.progress},
                )
        for job_id in requeued_job_ids:
            await self._sync_agent_job(job_id=job_id)
            await self._publish_generation_event(job_id=job_id, stage="queued", progress=0)
        for job_id in changed_job_ids:
            await self._sync_agent_job(job_id=job_id)
            await self._publish_generation_event(job_id=job_id, stage="failed", progress=0, level="error")

    async def approve_job(self, *, job_id: str) -> GenerationJobRead:
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            job = await repository.get_job(job_id)
            if job is None:
                raise ValueError(f"unknown generation job '{job_id}'")
            if job.status != GenerationJobStatus.COMPLETED.value:
                raise ValueError("only completed jobs can be approved for install")
            blockers = await self._approval_blockers(repository, job_id=job.id)
            if blockers:
                raise ValueError("generation job cannot be approved: " + "; ".join(blockers))
            await repository.update_job_with_log(
                job,
                status=GenerationJobStatus.REVIEW_REQUIRED,
                current_step="review",
                progress=100,
                install_blocked=False,
                clear_error=True,
                log_level="info",
                log_step="review",
                log_message="Generation job review approved for install.",
                log_context={"progress": 100},
            )
        await self._sync_agent_job(job_id=job_id)
        return await self.get_job(job_id=job_id)

    async def reject_job(self, *, job_id: str, reason: str) -> GenerationJobRead:
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            job = await repository.get_job(job_id)
            if job is None:
                raise ValueError(f"unknown generation job '{job_id}'")
            if job.status not in {GenerationJobStatus.COMPLETED.value, GenerationJobStatus.REVIEW_REQUIRED.value}:
                raise ValueError("only reviewable jobs can be rejected")
            await repository.update_job_with_log(
                job,
                status=GenerationJobStatus.REJECTED,
                current_step="rejected",
                progress=100,
                install_blocked=True,
                error_message=reason,
                log_level="warning",
                log_step="review",
                log_message="Generation job rejected.",
                log_context={"reason": reason, "progress": 100},
            )
        await self._sync_agent_job(job_id=job_id)
        return await self.get_job(job_id=job_id)

    async def install_job(self, *, job_id: str, enabled: bool) -> GenerationJobRead:
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            job = await repository.get_job(job_id)
            if job is None:
                raise ValueError(f"unknown generation job '{job_id}'")
            if job.status not in {GenerationJobStatus.REVIEW_REQUIRED.value, GenerationJobStatus.APPROVED.value}:
                raise ValueError("job must pass review before install")
            artifact = await repository.get_latest_artifact(job_id=job_id, stage="codegen", artifact_type="package")
            if artifact is None:
                raise ValueError("job does not contain an installable package artifact")
            package = WidgetPackagePayload.model_validate(decode_artifact_payload(artifact)["package"])

        plugin = await self.plugin_manager.get_plugin(job.widget_id)
        if plugin and plugin.installed:
            if plugin.is_core:
                raise ValueError("generated jobs cannot overwrite core widgets")
            await self.plugin_manager.update_widget(
                job.widget_id,
                WidgetPluginUpdateRequest(
                    package=package,
                    source_ref=f"generation-job:{job.id}",
                ),
            )
        else:
            await self.plugin_manager.install_widget(
                WidgetPluginInstallRequest(
                    package=package,
                    enabled=enabled,
                    source_type="generated",
                    source_ref=f"generation-job:{job.id}",
                )
            )

        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            record = await repository.get_job(job_id)
            if record is None:
                raise ValueError(f"unknown generation job '{job_id}'")
            await repository.update_job_with_log(
                record,
                status=GenerationJobStatus.INSTALLED,
                current_step="install",
                progress=100,
                install_blocked=False,
                clear_error=True,
                completed_at=datetime.now(timezone.utc),
                log_level="info",
                log_step="install",
                log_message="Generated widget package installed through the registry.",
                log_context={"widget_id": record.widget_id, "version": record.selected_version, "progress": 100},
            )
        await self._sync_agent_job(job_id=job_id)
        return await self.get_job(job_id=job_id)

    async def _execute_job(
        self,
        *,
        job_id: str,
        spec: WidgetSpecDraft | None,
        provider: AIProvider,
        model_id: str | None,
        idea: str | None = None,
        idea_prompt: str | None = None,
        idea_usage: dict[str, Any] | None = None,
        regeneration_hint: str | None = None,
    ) -> GenerationJobRead:
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            job = await repository.get_job(job_id)
            if job is None:
                raise ValueError(f"unknown generation job '{job_id}'")

            generation_mode = await self._provider_generation_mode(provider)
            selected_model = _resolve_provider_model(provider, model_id)
            job.generation_mode = generation_mode
            job.model_id = selected_model
            await session.commit()

            await repository.update_job(
                job,
                status=GenerationJobStatus.RUNNING,
                current_step="spec",
                progress=10,
                clear_error=True,
            )
            await self._sync_agent_job(job_id=job.id)
            await self._publish_generation_event(job_id=job.id, stage="spec", progress=10, generation_mode=generation_mode)

            if spec is None:
                # Idea-based jobs defer provider.draft_spec (which can run agent CLIs with
                # web research for minutes) until here, inside the worker, so the request
                # path that created the job never blocks on it.
                if not idea:
                    raise ValueError("generation job is missing both a spec and an idea to draft one from")
                idea_result = await provider.draft_spec(idea=idea, model_id=model_id)
                idea_prompt = str(idea_result.pop("idea_prompt", "")) or None
                idea_usage = idea_result.pop("usage", None)
                spec = WidgetSpecDraft.model_validate(idea_result)
                draft_notes = validate_widget_spec(spec)
                board_repository = BoardRepository(session)
                stage = await board_repository.create_staged_spec(
                    widget_id=spec.id,
                    stage="validated" if not draft_notes else "draft",
                    spec=spec.model_dump(mode="json"),
                    scaffold_preview=scaffold_preview(spec),
                    notes=draft_notes,
                )
                # Re-stamp the job onto the widget id the drafted spec actually settled
                # on, since the provisional id derived at creation time is only a
                # deterministic guess.
                await repository.update_job(job, stage_id=stage.id, widget_id=spec.id)
                await self._sync_agent_job(job_id=job.id)

            notes = validate_widget_spec(spec)
            if notes:
                raise ValueError("; ".join(notes))

            spec_payload = spec.model_dump(mode="json")
            await repository.add_artifact(
                job_id=job.id,
                widget_id=job.widget_id,
                artifact_version=job.artifact_version,
                stage="spec",
                artifact_type="normalized_spec",
                payload={
                    "spec": spec_payload,
                    "manifest_preview": build_manifest_preview_with_version(spec, version=job.selected_version),
                    "idea_prompt": idea_prompt,
                    "generation_mode": generation_mode,
                    "model_id": selected_model,
                    "usage": idea_usage,
                },
            )
            await repository.add_log(
                job_id=job.id,
                level="info",
                step="spec",
                message="Validated spec attached to generation job.",
                context={"stage_id": job.stage_id, "progress": 25, "generation_mode": generation_mode},
            )
            await repository.update_job(job, progress=25)
            await self._sync_agent_job(job_id=job.id)

            scaffold = self.scaffold_generator.generate(
                spec=spec,
                version=job.selected_version,
                artifact_version=job.artifact_version,
            )
            await repository.update_job(job, current_step="scaffold", progress=40)
            await self._sync_agent_job(job_id=job.id)
            await self._publish_generation_event(job_id=job.id, stage="scaffold", progress=40, generation_mode=generation_mode)
            await repository.add_artifact(
                job_id=job.id,
                widget_id=job.widget_id,
                artifact_version=job.artifact_version,
                stage="scaffold",
                artifact_type="preview",
                payload={
                    "files": [
                        {"path": file["path"], "language": file["language"], "content": ""}
                        for file in scaffold["files"]
                    ],
                    "preview": scaffold["preview"],
                    "generation_mode": generation_mode,
                    "model_id": selected_model,
                },
            )
            await repository.add_log(
                job_id=job.id,
                level="info",
                step="scaffold",
                message="Widget scaffold prepared.",
                context={"file_count": len(scaffold["files"]), "progress": 50, "generation_mode": generation_mode},
            )
            await repository.update_job(job, progress=50)
            await self._sync_agent_job(job_id=job.id)

            package = dict(scaffold["package"])
            files = [dict(file) for file in scaffold["files"]]
            provider_codegen = await provider.prepare_codegen(
                widget_spec=spec_payload,
                scaffold_files=scaffold["preview"]["files"],
                model_id=model_id,
            )
            fallback_error: str | None = None
            codegen_usage: dict[str, int] | None = None
            try:
                live_blueprint = await provider.generate_blueprint(
                    widget_spec=spec_payload,
                    model_id=model_id,
                    extra_guidance=regeneration_hint,
                )
                blueprint_meta = _extract_generation_metadata(live_blueprint)
                live_blueprint = _strip_generation_metadata(live_blueprint)
                validate_blueprint(live_blueprint)
                backend_result = await provider.generate_backend(
                    widget_spec=spec_payload,
                    blueprint=live_blueprint,
                    model_id=model_id,
                    extra_guidance=regeneration_hint,
                )
                live_backend = backend_result.source
                package["blueprint"] = live_blueprint
                package["backend_source"] = live_backend
                _replace_file_content(files, "view.blueprint.json", json.dumps(live_blueprint, indent=2) + "\n")
                _replace_file_content(files, "backend.py", live_backend)
                generation_mode = str(blueprint_meta.get("generation_mode") or "live")
                selected_model = str(blueprint_meta.get("model_id") or selected_model)
                codegen_usage = _combine_usage(blueprint_meta.get("usage"), backend_result.usage)
                provider_codegen = dict(provider_codegen) | {
                    "generation_mode": generation_mode,
                    "model_id": selected_model,
                    "live_blueprint": True,
                    "live_backend": True,
                    "usage": codegen_usage,
                }
            except (NotImplementedError, AIClientError) as exc:
                generation_mode = "offline"
                fallback_error = str(exc)
                codegen_usage = None
                package = dict(scaffold["package"])
                files = [dict(file) for file in scaffold["files"]]
                provider_codegen = dict(provider_codegen) | {
                    "generation_mode": "offline",
                    "model_id": selected_model,
                    "live_blueprint": False,
                    "live_backend": False,
                    "fallback_error": fallback_error,
                }
                await repository.add_log(
                    job_id=job.id,
                    level="warning",
                    step="codegen",
                    message="Live generation unavailable; falling back to deterministic template scaffold.",
                    context={"error": fallback_error, "progress": 65},
                )

            job.generation_mode = generation_mode
            job.model_id = selected_model
            await session.commit()
            await repository.update_job(job, current_step="codegen", progress=70)
            await self._sync_agent_job(job_id=job.id)
            await self._publish_generation_event(job_id=job.id, stage="codegen", progress=70, generation_mode=generation_mode)

            manifest = package["manifest"]
            config = _default_config_from_schema(package["config_schema"])
            dry_run = await dry_run_backend(
                str(package["backend_source"]),
                manifest=manifest,
                config=config,
                timeout=float(manifest.get("runtime_policy", {}).get("start_timeout_seconds", 10)),
            )
            review_issues = _issues_from_dry_run(dry_run)
            state = dry_run.get("state") if dry_run.get("ok") and isinstance(dry_run.get("state"), dict) else None
            if state is not None and isinstance(package.get("blueprint"), dict):
                review_issues.extend(_binding_warnings(blueprint=package["blueprint"], state=state))

            await repository.add_artifact(
                job_id=job.id,
                widget_id=job.widget_id,
                artifact_version=job.artifact_version,
                stage="codegen",
                artifact_type="package",
                payload={
                    "files": files,
                    "package": package,
                    "provider": provider_codegen,
                    "generation_mode": generation_mode,
                    "model_id": selected_model,
                    "dry_run": dry_run,
                    "usage": codegen_usage,
                },
            )
            await repository.add_log(
                job_id=job.id,
                level="info",
                step="codegen",
                message="Generated package artifact version created.",
                context={"artifact_version": job.artifact_version, "progress": 80, "generation_mode": generation_mode},
            )
            await repository.update_job(job, progress=80)
            await self._sync_agent_job(job_id=job.id)

            await repository.update_job(job, current_step="review", progress=90)
            await self._sync_agent_job(job_id=job.id)
            await self._publish_generation_event(job_id=job.id, stage="review", progress=90, generation_mode=generation_mode)
            review = await provider.review_package(widget_spec=spec_payload, package=package, model_id=model_id)
            review = _merge_review_issues(
                review,
                issues=review_issues,
                generation_mode=generation_mode,
                model_id=selected_model,
                dry_run=dry_run,
            )
            await repository.add_artifact(
                job_id=job.id,
                widget_id=job.widget_id,
                artifact_version=job.artifact_version,
                stage="review",
                artifact_type="report",
                payload=review,
            )
            review_usage = review.get("usage") if isinstance(review.get("usage"), dict) else None
            job_token_usage = _combine_usage(idea_usage, codegen_usage, review_usage)
            job.token_usage_json = json.dumps(job_token_usage) if job_token_usage else None
            await session.commit()
            await repository.update_job_with_log(
                job,
                status=GenerationJobStatus.COMPLETED,
                current_step="completed",
                progress=100,
                install_blocked=True,
                completed_at=datetime.now(timezone.utc),
                log_level="info",
                log_step="completed",
                log_message="Generation completed. Install remains blocked pending review approval.",
                log_context={"provider_id": provider.provider_id, "progress": 100, "generation_mode": generation_mode},
            )
            await self._sync_agent_job(job_id=job.id)
            await self._publish_generation_event(job_id=job.id, stage="completed", progress=100, generation_mode=generation_mode)
        return await self.get_job(job_id=job_id)

    async def _load_queued_input(self, job_id: str) -> QueuedGenerationInput:
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            record = await repository.get_job(job_id)
            if record is None or not record.queued_input_json:
                raise ValueError("queued generation input is no longer available")
            return _deserialize_queued_input(record.queued_input_json)

    async def _provider_generation_mode(self, provider: AIProvider) -> str:
        await self._refresh_provider_credentials(provider)
        try:
            health = await provider.health()
        except Exception:
            return "offline"
        return str(health.get("mode") or "offline")

    async def _refresh_provider_credentials(self, provider: AIProvider) -> None:
        list_credentials = getattr(self.settings_service, "list_credential_secrets_by_provider", None)
        if not callable(list_credentials):
            return
        credentials = await list_credentials()
        set_credentials = getattr(provider, "set_credentials", None)
        if callable(set_credentials):
            set_credentials(credentials)

    async def _publish_generation_event(
        self,
        *,
        job_id: str,
        stage: str,
        progress: int,
        generation_mode: str | None = None,
        level: str = "info",
        message: str | None = None,
    ) -> None:
        if self.event_bus is None:
            return
        payload = {
            "job_id": job_id,
            "stage": stage,
            "progress": max(0, min(100, progress)),
            "generation_mode": generation_mode,
        }
        try:
            await self.event_bus.publish_event(
                f"generation.{stage}",
                category="generation",
                level=level,
                message=message,
                source={"component": "generation_pipeline", "job_id": job_id},
                payload=payload,
                persistence=RuntimeEventPersistence.EPHEMERAL,
                visibility=RuntimeEventVisibility.BOTH,
                replayable=True,
            )
        except Exception:
            logger.exception("failed to publish generation event for job %s stage %s", job_id, stage)

    async def _refine_spec_with_provider(
        self,
        *,
        provider: AIProvider,
        spec: WidgetSpecDraft,
        blueprint: dict[str, Any] | None,
        feedback: str,
        model_id: str | None,
    ) -> tuple[WidgetSpecDraft, dict[str, Any]]:
        await self._refresh_provider_credentials(provider)
        refine = getattr(provider, "refine_spec", None)
        if callable(refine):
            try:
                result = await refine(
                    feedback=feedback,
                    widget_spec=spec.model_dump(mode="json"),
                    blueprint=blueprint or {},
                    model_id=model_id,
                )
                refined = WidgetSpecDraft.model_validate(_strip_generation_metadata(dict(result)))
                return refined, {
                    "generation_mode": str(result.get("generation_mode", "live")),
                    "model_id": str(result.get("model_id") or _resolve_provider_model(provider, model_id)),
                    "source": "provider",
                }
            except (NotImplementedError, AIClientError):
                pass
        category = _categorize_feedback(feedback)
        refined = _refine_spec_from_feedback(spec=spec, feedback=feedback, category=category)
        return refined, {
            "generation_mode": "offline",
            "model_id": _resolve_provider_model(provider, model_id),
            "source": "heuristic",
        }

    async def _approval_blockers(self, repository: GenerationRepository, *, job_id: str) -> list[str]:
        artifact = await repository.get_latest_artifact(job_id=job_id, stage="review", artifact_type="report")
        if artifact is None:
            return ["missing review artifact"]
        review = decode_artifact_payload(artifact)
        blockers: list[str] = []
        dry_run = review.get("dry_run")
        if isinstance(dry_run, dict) and dry_run.get("ok") is False:
            blockers.append(f"backend dry-run failed: {dry_run.get('error') or 'unknown error'}")
        for issue in review.get("issues", []):
            if not isinstance(issue, dict):
                continue
            if str(issue.get("severity")) == "critical":
                message = str(issue.get("message") or issue.get("area") or "critical review issue")
                blockers.append(message)
        return blockers
    async def _sync_agent_job(self, *, job_id: str) -> None:
        if self.agent_registry is None:
            return
        job = await self.get_job(job_id=job_id)
        await self.agent_registry.upsert_generation_job(job)

    async def _resolve_spec_source(
        self,
        *,
        payload: GenerationJobCreateRequest,
    ) -> _ResolvedSpecSource:
        if payload.idea:
            # Idea-based jobs no longer call provider.draft_spec here: that call can run
            # agent CLIs with web research for minutes, which is too slow for the request
            # path. Instead we derive a deterministic provisional widget id (same
            # heuristic the offline provider path uses) so the job can be persisted and
            # returned immediately; the worker drafts the real spec and re-stamps the
            # widget id once drafting completes.
            widget_id = _provisional_widget_id(payload.idea)
            return _ResolvedSpecSource(widget_id=widget_id, spec=None, stage_id=None, idea=payload.idea)

        async with self.session_factory() as session:
            if payload.regenerate_from_job_id:
                generation_repository = GenerationRepository(session)
                job = await generation_repository.get_job(payload.regenerate_from_job_id)
                if job is None:
                    raise ValueError(f"unknown generation job '{payload.regenerate_from_job_id}'")
                if job.stage_id is None:
                    raise ValueError("cannot regenerate a job without an associated validated spec")
                payload = payload.model_copy(update={"stage_id": job.stage_id, "regenerate_from_job_id": None})

            stage_record = await session.get(StagedWidgetSpecRecord, payload.stage_id)
            if stage_record is None:
                raise ValueError(f"unknown spec stage '{payload.stage_id}'")
            notes = json.loads(stage_record.validation_notes or "[]")
            if stage_record.stage != "validated" or notes:
                raise ValueError("spec stage must be validated before generation can run")
            spec = WidgetSpecDraft.model_validate(json.loads(stage_record.spec_json))
            return _ResolvedSpecSource(widget_id=spec.id, spec=spec, stage_id=stage_record.id, idea=None)

    async def _serialize_job(self, session: AsyncSession, job_id: str) -> GenerationJobRead:
        repository = GenerationRepository(session)
        job = await repository.get_job(job_id)
        if job is None:
            raise ValueError(f"unknown generation job '{job_id}'")
        artifacts = await repository.list_artifacts(job_id)
        logs = await repository.list_logs(job_id)
        install_target = await self._build_install_target(job.widget_id, job.selected_version)
        diff_preview = await self._build_diff_preview(session=session, job_id=job_id, widget_id=job.widget_id)
        serialized = serialize_job(
            job,
            artifacts=artifacts,
            logs=logs,
            install_target=install_target,
            diff_preview=diff_preview,
        )
        return serialized.model_copy(
            update={
                "generation_mode": job.generation_mode,
                "model_id": job.model_id,
            }
        )

    async def _build_diff_preview(
        self,
        *,
        session: AsyncSession,
        job_id: str,
        widget_id: str,
    ) -> list[GenerationArtifactDiffRead]:
        repository = GenerationRepository(session)
        artifact = await repository.get_latest_artifact(job_id=job_id, stage="codegen", artifact_type="package")
        if artifact is None:
            return []
        current_package = decode_artifact_payload(artifact).get("package")
        if current_package is None:
            return []

        baseline = self.plugin_manager.read_installed_package(widget_id)
        if baseline is None:
            previous = await repository.get_latest_package_artifact_for_widget(widget_id=widget_id, exclude_job_id=job_id)
            baseline = decode_artifact_payload(previous).get("package") if previous is not None else None

        return _build_package_diff_preview(baseline=baseline, candidate=current_package)

    async def _build_install_target(self, widget_id: str, version: str) -> dict[str, Any]:
        plugin = await self.plugin_manager.get_plugin(widget_id)
        if plugin and plugin.installed:
            return {
                "action": "update",
                "widget_id": widget_id,
                "current_version": plugin.version,
                "next_version": version,
            }
        return {
            "action": "install",
            "widget_id": widget_id,
            "current_version": None,
            "next_version": version,
        }

    async def _select_provider(self, requested_provider_id: str | None, fallback_provider_ids: list[str]) -> AIProvider:
        settings = await self.settings_service.read()
        enabled_provider_ids = set(settings.ai.enabled_provider_ids)
        preferred_provider_id = requested_provider_id or settings.ai.default_provider_id
        fallback_chain = fallback_provider_ids or settings.ai.fallback_provider_ids
        if preferred_provider_id is not None:
            chain = [preferred_provider_id, *fallback_chain]
        else:
            chain = [*fallback_chain, *self.providers.keys()]
        seen: set[str] = set()
        for provider_id in chain:
            if provider_id in seen:
                continue
            seen.add(provider_id)
            if provider_id not in enabled_provider_ids:
                continue
            provider = provider_from_id(provider_id, self.providers)
            await self._refresh_provider_credentials(provider)
            health = await provider.health()
            if str(health.get("status", "")).lower() not in {"unavailable", "error"}:
                return provider
        raise ValueError("no available AI provider found")

    async def _next_artifact_version(self, widget_id: str) -> int:
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            return await repository.next_artifact_version(widget_id)

    async def _resolve_version(self, *, widget_id: str, requested_version: str | None) -> str:
        if requested_version:
            return requested_version
        plugin = await self.plugin_manager.get_plugin(widget_id)
        if plugin and plugin.installed:
            return _bump_patch_version(plugin.version)
        return "0.1.0"

    def _creation_lock(self, widget_id: str) -> asyncio.Lock:
        lock = self._creation_locks.get(widget_id)
        if lock is None:
            lock = asyncio.Lock()
            self._creation_locks[widget_id] = lock
        return lock


def _provisional_widget_id(idea: str) -> str:
    """Derive a deterministic widget id from an idea without calling the AI provider.

    Mirrors the heuristic the offline provider path uses (see `_detect_title` /
    `_slugify` in `ai/providers.py`) so the id assigned at job-creation time is stable
    and collision-safe the same way ids are today; the worker re-stamps this once the
    real spec is drafted.
    """

    normalized = " ".join(idea.split())
    return _slugify(_detect_title(normalized))


def _serialize_queued_input(value: QueuedGenerationInput) -> str:
    return json.dumps(
        {
            "job_id": value.job_id,
            "spec": value.spec.model_dump(mode="json") if value.spec is not None else None,
            "provider_id": value.provider_id,
            "model_id": value.model_id,
            "idea_prompt": value.idea_prompt,
            "idea_usage": value.idea_usage,
            "idea": value.idea,
            "regeneration_hint": value.regeneration_hint,
        }
    )


def _deserialize_queued_input(value: str) -> QueuedGenerationInput:
    payload = json.loads(value)
    spec_payload = payload.get("spec")
    return QueuedGenerationInput(
        job_id=str(payload["job_id"]),
        spec=WidgetSpecDraft.model_validate(spec_payload) if spec_payload is not None else None,
        provider_id=str(payload["provider_id"]),
        model_id=payload.get("model_id"),
        idea_prompt=payload.get("idea_prompt"),
        idea_usage=payload.get("idea_usage"),
        idea=payload.get("idea"),
        regeneration_hint=payload.get("regeneration_hint"),
    )


def _resolve_provider_model(provider: AIProvider, model_id: str | None) -> str | None:
    if model_id:
        return model_id
    default = getattr(provider, "default_model_id", None)
    if default:
        return str(default)
    supported = getattr(provider, "supported_model_ids", ())
    return str(supported[0]) if supported else None


def _extract_generation_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: payload.get(key) for key in ("generation_mode", "model_id", "usage") if key in payload}


def _strip_generation_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in {"generation_mode", "model_id", "usage"}}


def _combine_usage(*usages: dict[str, Any] | None) -> dict[str, int] | None:
    combined = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
    found = False
    for usage in usages:
        if not isinstance(usage, dict):
            continue
        found = True
        combined["input_tokens"] += int(usage.get("input_tokens") or 0)
        combined["output_tokens"] += int(usage.get("output_tokens") or 0)
        combined["calls"] += int(usage.get("calls") or 0)
    return combined if found else None


def _replace_file_content(files: list[dict[str, Any]], suffix: str, content: str) -> None:
    for file in files:
        if str(file.get("path", "")).endswith(suffix):
            file["content"] = content
            return


def _artifact_blueprint(artifact: Any | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    package = decode_artifact_payload(artifact).get("package")
    if isinstance(package, dict) and isinstance(package.get("blueprint"), dict):
        return package["blueprint"]
    return None


def _issues_from_dry_run(dry_run: dict[str, Any]) -> list[dict[str, str]]:
    if dry_run.get("ok") is not False:
        return []
    return [
        {
            "severity": "critical",
            "area": "contract",
            "message": f"Generated backend failed dry-run: {dry_run.get('error') or 'unknown error'}",
            "fix_hint": "Fix backend.py so start() and get_state() complete without crashing or hanging.",
        }
    ]


def _binding_warnings(*, blueprint: dict[str, Any], state: dict[str, Any]) -> list[dict[str, str]]:
    try:
        paths = collect_binding_paths(validate_blueprint(blueprint))
    except ValueError as exc:
        return [
            {
                "severity": "critical",
                "area": "bindings",
                "message": f"Generated blueprint failed validation before binding check: {exc}",
                "fix_hint": "Return a valid view.blueprint.json document that matches the schema.",
            }
        ]
    top_level = {_top_level_path(path) for path in paths}
    missing = sorted(path for path in top_level if path and path not in state)
    return [
        {
            "severity": "warning",
            "area": "bindings",
            "message": f"Blueprint binding top-level path '{path}' was not returned by backend dry-run state.",
            "fix_hint": f"Update get_state() to include '{path}' or update view.blueprint.json bindings.",
        }
        for path in missing
    ]


def _top_level_path(path: str) -> str:
    return path.split(".", 1)[0].split("[", 1)[0]


def _merge_review_issues(
    review: dict[str, Any],
    *,
    issues: list[dict[str, str]],
    generation_mode: str,
    model_id: str | None,
    dry_run: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(review)
    existing = [issue for issue in merged.get("issues", []) if isinstance(issue, dict)]
    merged["issues"] = [*existing, *issues]
    merged["generation_mode"] = generation_mode
    merged["model_id"] = model_id
    merged["dry_run"] = dry_run
    if any(issue.get("severity") == "critical" for issue in merged["issues"]):
        merged["approved_for_install_recommendation"] = False
    return merged


def _changed_spec_fields(before: WidgetSpecDraft, after: WidgetSpecDraft) -> list[str]:
    before_payload = before.model_dump(mode="json")
    after_payload = after.model_dump(mode="json")
    return sorted(key for key in after_payload if before_payload.get(key) != after_payload.get(key))


def _derive_feedback_tags(*, changed_fields: list[str], feedback: str) -> list[str]:
    tags: list[str] = []
    field_tags = {
        "name": "name",
        "min_size": "sizing",
        "preferred_size": "sizing",
        "renderer_type": "ui",
        "output_schema": "feature",
        "refresh_policy": "feature",
        "lifecycle_policy": "feature",
        "category": "feature",
        "permissions": "feature",
        "description": "feature",
    }
    for field in changed_fields:
        tag = field_tags.get(field, "feature")
        if tag not in tags:
            tags.append(tag)
    if not tags:
        tags.append(_categorize_feedback(feedback))
    return tags


def _primary_feedback_category(tags: list[str]) -> str:
    # Most specific signal wins; "feature" is the catch-all fallback and must
    # not outrank name/sizing/ui just because the always-appended description
    # change contributes a "feature" tag.
    for candidate in ("name", "sizing", "ui"):
        if candidate in tags:
            return candidate
    return "feature"


def _format_spec_diff_summary(changed_fields: list[str]) -> str:
    if not changed_fields:
        return "No spec fields changed."
    return "Changed fields: " + ", ".join(changed_fields)

def _bump_patch_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return version
    major, minor, patch = (int(part) for part in parts)
    return f"{major}.{minor}.{patch + 1}"


def _build_test_box_payload(job: GenerationJobRead) -> GenerationTestBoxRead | None:
    spec_payload: dict[str, Any] | None = None
    package_payload: dict[str, Any] | None = None
    files: list[GenerationArtifactFileRead] = []

    for artifact in job.artifacts:
        if artifact.stage == "spec" and artifact.artifact_type == "normalized_spec" and artifact.payload:
            raw_spec = artifact.payload.get("spec")
            if isinstance(raw_spec, dict):
                spec_payload = raw_spec
        if artifact.stage == "codegen" and artifact.artifact_type == "package" and artifact.payload:
            raw_package = artifact.payload.get("package")
            if isinstance(raw_package, dict):
                package_payload = raw_package
                files = artifact.files

    if spec_payload is None or package_payload is None:
        return None

    manifest = package_payload["manifest"]
    output_schema = spec_payload.get("output_schema") if isinstance(spec_payload.get("output_schema"), dict) else {}
    initial_state = {
        "kind": job.widget_id,
        "title": manifest["name"],
        "category": manifest["category"],
        "description": manifest["description"],
        "output": {
            key: f"sample_{index + 1}"
            for index, key in enumerate(_flatten_output_schema_keys(output_schema) or ["primary"])
        },
    }
    config_schema = package_payload["config_schema"]
    return GenerationTestBoxRead(
        job_id=job.id,
        widget_id=job.widget_id,
        stage_id=job.stage_id,
        name=manifest["name"],
        description=manifest["description"],
        category=manifest["category"],
        size=manifest["preferred_size"],
        allowed_sizes=manifest["allowed_sizes"],
        manifest=manifest,
        config_schema=config_schema,
        renderer=manifest["renderer"],
        service=manifest["service"],
        initial_config=_default_config_from_schema(config_schema),
        initial_state=initial_state,
        files=files,
        install_blocked=job.install_blocked,
        review_required=True,
    )


def _flatten_output_schema_keys(value: dict[str, Any], *, prefix: str = "") -> list[str]:
    keys: list[str] = []
    for key, child in value.items():
        child_key = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            keys.extend(_flatten_output_schema_keys(child, prefix=child_key))
        else:
            keys.append(child_key)
    return keys


def _default_config_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}
    config: dict[str, Any] = {}
    for key, definition in properties.items():
        if not isinstance(definition, dict) or "default" not in definition:
            continue
        config[key] = definition["default"]
    return config


def _categorize_feedback(feedback: str) -> str:
    lowered = feedback.lower()
    if any(token in lowered for token in ("rename", "call it", "title", "label", "name")):
        return "name"
    if any(
        token in lowered
        for token in (
            "1x1",
            "1x2",
            "2x2",
            "4x2",
            "2x4",
            "4x4",
            "size",
            "compact",
            "small",
            "wide",
            "tall",
            "large",
            "bigger",
            "smaller",
        )
    ):
        return "sizing"
    if any(
        token in lowered
        for token in (
            "ui",
            "visual",
            "layout",
            "renderer",
            "chart",
            "graph",
            "table",
            "list",
            "card",
            "color",
            "style",
        )
    ):
        return "ui"
    return "feature"


def _refine_spec_from_feedback(*, spec: WidgetSpecDraft, feedback: str, category: str) -> WidgetSpecDraft:
    payload = spec.model_dump(mode="json")
    lowered = feedback.lower()
    extracted_name = _extract_feedback_name(feedback)
    if extracted_name is not None:
        payload["name"] = extracted_name

    sizes = _detect_feedback_sizes(lowered)
    if sizes is not None:
        payload["min_size"], payload["preferred_size"] = sizes

    renderer_type = _detect_renderer_type(lowered)
    if renderer_type is not None:
        payload["renderer_type"] = renderer_type

    refresh_policy = _detect_feedback_refresh_policy(lowered)
    if refresh_policy is not None:
        payload["refresh_policy"] = refresh_policy

    lifecycle_policy = dict(payload["lifecycle_policy"])
    if any(token in lowered for token in ("remember", "persist", "stateful", "cache")):
        lifecycle_policy["stateful"] = True
    if any(token in lowered for token in ("expire", "ttl", "temporary")):
        lifecycle_policy["expires"] = True
        lifecycle_policy.setdefault("default_ttl_seconds", 3600)
    if any(token in lowered for token in ("never expire", "permanent")):
        lifecycle_policy["expires"] = False
        lifecycle_policy["default_ttl_seconds"] = None
    payload["lifecycle_policy"] = lifecycle_policy

    category_hint = _detect_feedback_spec_category(lowered)
    if category_hint is not None:
        payload["category"] = category_hint

    permissions = set(payload["permissions"])
    if any(token in lowered for token in ("api", "http", "network", "remote", "feed")):
        permissions.add("network")
    if any(token in lowered for token in ("storage", "store", "remember", "persist", "personal")):
        permissions.add("storage")
    if any(token in lowered for token in ("offline", "local only", "no network")):
        permissions.discard("network")
    payload["permissions"] = sorted(permissions) or ["network"]

    output_schema = dict(payload["output_schema"])
    for key in _detect_output_fields(lowered):
        output_schema.setdefault(key, "string")
    payload["output_schema"] = output_schema

    payload["description"] = _refined_description(
        description=payload["description"],
        category=category,
        feedback=feedback,
    )
    return WidgetSpecDraft.model_validate(payload)


def _extract_feedback_name(feedback: str) -> str | None:
    quoted = re.findall(r"[\"']([^\"']{1,80})[\"']", feedback)
    if quoted:
        return " ".join(quoted[0].split())
    match = re.search(r"(?:rename|call it|title|label|name)\s+(?:it\s+)?(?:to\s+|as\s+)?([A-Za-z0-9][A-Za-z0-9 _-]{1,79})", feedback, re.IGNORECASE)
    if match is None:
        return None
    candidate = re.split(r"\s+(?:and|with|but|while)\s+", match.group(1), maxsplit=1)[0]
    return " ".join(candidate.strip(" .").split()) or None


def _detect_feedback_sizes(lowered: str) -> tuple[str, str] | None:
    exact_sizes = ("1x1", "1x2", "2x2", "4x2", "2x4", "4x4")
    for size in exact_sizes:
        if size in lowered:
            if size == "1x1":
                return "1x1", "1x1"
            if size == "1x2":
                return "1x1", "1x2"
            if size == "2x2":
                return "2x2", "2x2"
            if size == "4x2":
                return "2x2", "4x2"
            if size == "2x4":
                return "1x2", "2x4"
            return "2x2", "4x4"
    if any(token in lowered for token in ("compact", "small", "smaller", "badge")):
        return "1x1", "1x2"
    if any(token in lowered for token in ("wide", "ticker", "horizontal")):
        return "2x2", "4x2"
    if any(token in lowered for token in ("tall", "vertical", "feed")):
        return "1x2", "2x4"
    if any(token in lowered for token in ("large", "bigger", "dashboard", "dense")):
        return "2x2", "4x4"
    return None


def _detect_renderer_type(lowered: str) -> str | None:
    if any(token in lowered for token in ("chart", "graph", "sparkline")):
        return "chart"
    if "table" in lowered:
        return "table"
    if any(token in lowered for token in ("list", "feed", "timeline")):
        return "list"
    if "card" in lowered:
        return "card"
    return None


def _detect_feedback_refresh_policy(lowered: str) -> dict[str, Any] | None:
    if any(token in lowered for token in ("manual", "on demand", "button refresh")):
        return {"mode": "manual", "interval_seconds": 0}
    if any(token in lowered for token in ("live", "realtime", "real-time", "stream")):
        return {"mode": "live", "interval_seconds": 0}
    match = re.search(r"every\s+(\d+)\s*(second|seconds|minute|minutes|hour|hours)", lowered)
    if match is None:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    multiplier = 1 if unit.startswith("second") else 60 if unit.startswith("minute") else 3600
    return {"mode": "interval", "interval_seconds": amount * multiplier}


def _detect_feedback_spec_category(lowered: str) -> str | None:
    if any(token in lowered for token in ("sport", "ipl", "f1", "football", "score")):
        return "sports"
    if any(token in lowered for token in ("news", "headline", "briefing")):
        return "news"
    if any(token in lowered for token in ("trend", "reddit", "hacker news", "hackernews")):
        return "trending"
    if any(token in lowered for token in ("countdown", "timer", "deadline")):
        return "countdown"
    if any(token in lowered for token in ("pin", "note", "todo", "personal")):
        return "pinboard"
    return None


def _detect_output_fields(lowered: str) -> list[str]:
    fields: list[str] = []
    for token, field in (
        ("score", "score"),
        ("headline", "headline"),
        ("alert", "alert"),
        ("warning", "alert"),
        ("count", "count"),
        ("deadline", "deadline"),
        ("due", "deadline"),
        ("temperature", "temperature"),
        ("metric", "metric"),
        ("trend", "trend"),
        ("status", "status"),
        ("summary", "summary"),
    ):
        if token in lowered and field not in fields:
            fields.append(field)
    return fields


def _refined_description(*, description: str, category: str, feedback: str) -> str:
    compact_feedback = " ".join(feedback.split())
    if len(compact_feedback) > 140:
        compact_feedback = f"{compact_feedback[:137].rstrip()}..."
    suffix = f"Feedback refinement ({category}): {compact_feedback}"
    if suffix in description:
        return description
    return f"{description} {suffix}"


def _build_package_diff_preview(
    *,
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any],
) -> list[GenerationArtifactDiffRead]:
    files = [
        ("manifest.json", _normalize_json(candidate["manifest"]), _normalize_json((baseline or {}).get("manifest"))),
        (
            "config.schema.json",
            _normalize_json(candidate["config_schema"]),
            _normalize_json((baseline or {}).get("config_schema")),
        ),
        ("backend.py", candidate["backend_source"], ((baseline or {}).get("backend_source") or "")),
    ]
    if candidate.get("blueprint") is not None:
        files.append(
            (
                "view.blueprint.json",
                _normalize_json(candidate["blueprint"]),
                _normalize_json((baseline or {}).get("blueprint")),
            )
        )
    else:
        files.append(("renderer.tsx", candidate.get("renderer_source") or "", ((baseline or {}).get("renderer_source") or "")))
    diff_items: list[GenerationArtifactDiffRead] = []
    for path, new_text, old_text in files:
        diff_lines = list(
            unified_diff(
                (old_text or "").splitlines(),
                (new_text or "").splitlines(),
                fromfile=f"current/{path}",
                tofile=f"generated/{path}",
                lineterm="",
            )
        )
        changed = bool(diff_lines)
        summary = "new artifact" if not old_text else ("changed" if changed else "unchanged")
        diff_items.append(
            GenerationArtifactDiffRead(
                path=path,
                changed=changed,
                summary=summary,
                diff="\n".join(diff_lines),
            )
        )
    return diff_items


def _normalize_json(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, indent=2, sort_keys=True) + "\n"
