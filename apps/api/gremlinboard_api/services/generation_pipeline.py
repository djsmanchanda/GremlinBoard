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

from gremlinboard_api.ai.providers import AIProvider, ClaudeProvider, CodexProvider, provider_from_id
from gremlinboard_api.models.tables import StagedWidgetSpecRecord
from gremlinboard_api.repositories.board import BoardRepository
from gremlinboard_api.repositories.generation import (
    GenerationRepository,
    decode_artifact_payload,
    serialize_job,
)
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
    GenerationPipelinePreviewRead,
    WidgetPackagePayload,
    WidgetPluginInstallRequest,
    WidgetPluginUpdateRequest,
    WidgetSpecDraft,
)
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
    spec: WidgetSpecDraft
    provider_id: str
    model_id: str | None
    idea_prompt: str | None


class GenerationPipelineService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        plugin_manager: PluginManagerService,
        settings_service: SystemSettingsService,
        agent_registry: "AgentRegistry | None" = None,
    ) -> None:
        self.session_factory = session_factory
        self.plugin_manager = plugin_manager
        self.settings_service = settings_service
        self.agent_registry = agent_registry
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
            await self._fail_interrupted_jobs()
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
            "queued_input_count": len(self._queued_inputs),
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

    async def create_job(self, payload: GenerationJobCreateRequest) -> GenerationJobRead:
        await self._ensure_worker_started()
        provider = await self._select_provider(payload.provider_id, payload.fallback_provider_ids)
        spec, stage_id, idea_prompt = await self._resolve_spec_source(payload=payload, provider=provider)
        async with self._creation_lock(spec.id):
            artifact_version = await self._next_artifact_version(spec.id)
            selected_version = await self._resolve_version(widget_id=spec.id, requested_version=payload.version)

            async with self.session_factory() as session:
                repository = GenerationRepository(session)
                job = await repository.create_job_with_log(
                    widget_id=spec.id,
                    provider_id=provider.provider_id,
                    requested_provider_id=payload.provider_id,
                    stage_id=stage_id,
                    idea=payload.idea,
                    artifact_version=artifact_version,
                    selected_version=selected_version,
                    current_step="queued",
                    progress=0,
                    log_level="info",
                    log_step="queued",
                    log_message="Generation job queued.",
                    log_context={
                        "stage_id": stage_id,
                        "provider_id": provider.provider_id,
                        "model_id": payload.model_id,
                        "progress": 0,
                    },
                )

        self._queued_inputs[job.id] = QueuedGenerationInput(
            job_id=job.id,
            spec=spec,
            provider_id=provider.provider_id,
            model_id=payload.model_id,
            idea_prompt=idea_prompt,
        )
        queued_job = await self.get_job(job_id=job.id)
        await self._sync_agent_job(job_id=job.id)
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
            refined_spec = _refine_spec_from_feedback(
                spec=previous_spec,
                feedback=payload.feedback,
                category=category,
            )
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
                    "feedback": payload.feedback,
                    "next_stage_id": stage.id,
                },
            )
            metadata = {
                "source_job_id": source_job.id,
                "source_artifact_version": artifact.artifact_version,
                "refined_stage_id": stage.id,
                "category": category,
                "feedback": payload.feedback,
                "refined_spec": refined_spec.model_dump(mode="json"),
            }

        queued_job = await self.create_job(
            GenerationJobCreateRequest(
                provider_id=payload.provider_id,
                model_id=payload.model_id,
                fallback_provider_ids=payload.fallback_provider_ids,
                stage_id=stage.id,
            )
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
                        raise ValueError("queued generation input is no longer available")
                    provider = provider_from_id(queued_input.provider_id, self.providers)
                    await self._execute_job(
                        job_id=queued_input.job_id,
                        spec=queued_input.spec,
                        provider=provider,
                        model_id=queued_input.model_id,
                        idea_prompt=queued_input.idea_prompt,
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

    async def _fail_interrupted_jobs(self) -> None:
        changed_job_ids: list[str] = []
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            records = await repository.list_jobs_by_status(
                {GenerationJobStatus.QUEUED, GenerationJobStatus.RUNNING}
            )
            for record in records:
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
        for job_id in changed_job_ids:
            await self._sync_agent_job(job_id=job_id)

    async def approve_job(self, *, job_id: str) -> GenerationJobRead:
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            job = await repository.get_job(job_id)
            if job is None:
                raise ValueError(f"unknown generation job '{job_id}'")
            if job.status != GenerationJobStatus.COMPLETED.value:
                raise ValueError("only completed jobs can be approved for install")
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
        spec: WidgetSpecDraft,
        provider: AIProvider,
        model_id: str | None,
        idea_prompt: str | None,
    ) -> GenerationJobRead:
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            job = await repository.get_job(job_id)
            if job is None:
                raise ValueError(f"unknown generation job '{job_id}'")

            await repository.update_job(
                job,
                status=GenerationJobStatus.RUNNING,
                current_step="spec",
                progress=10,
                clear_error=True,
            )
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
                },
            )
            await repository.add_log(
                job_id=job.id,
                level="info",
                step="spec",
                message="Validated spec attached to generation job.",
                context={"stage_id": job.stage_id, "progress": 25},
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
                },
            )
            await repository.add_log(
                job_id=job.id,
                level="info",
                step="scaffold",
                message="Widget scaffold prepared.",
                context={"file_count": len(scaffold["files"]), "progress": 50},
            )
            await repository.update_job(job, progress=50)
            await self._sync_agent_job(job_id=job.id)

            provider_codegen = await provider.prepare_codegen(
                widget_spec=spec_payload,
                scaffold_files=scaffold["preview"]["files"],
                model_id=model_id,
            )
            await repository.update_job(job, current_step="codegen", progress=70)
            await self._sync_agent_job(job_id=job.id)
            await repository.add_artifact(
                job_id=job.id,
                widget_id=job.widget_id,
                artifact_version=job.artifact_version,
                stage="codegen",
                artifact_type="package",
                payload={
                    "files": scaffold["files"],
                    "package": scaffold["package"],
                    "provider": provider_codegen,
                },
            )
            await repository.add_log(
                job_id=job.id,
                level="info",
                step="codegen",
                message="Generated package artifact version created.",
                context={"artifact_version": job.artifact_version, "progress": 80},
            )
            await repository.update_job(job, progress=80)
            await self._sync_agent_job(job_id=job.id)

            review = await provider.review_package(widget_spec=spec_payload, package=scaffold["package"], model_id=model_id)
            await repository.add_artifact(
                job_id=job.id,
                widget_id=job.widget_id,
                artifact_version=job.artifact_version,
                stage="review",
                artifact_type="report",
                payload=review,
            )
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
                log_context={"provider_id": provider.provider_id, "progress": 100},
            )
            await self._sync_agent_job(job_id=job.id)
        return await self.get_job(job_id=job_id)

    async def _sync_agent_job(self, *, job_id: str) -> None:
        if self.agent_registry is None:
            return
        job = await self.get_job(job_id=job_id)
        await self.agent_registry.upsert_generation_job(job)

    async def _resolve_spec_source(
        self,
        *,
        payload: GenerationJobCreateRequest,
        provider: AIProvider,
    ) -> tuple[WidgetSpecDraft, str | None, str | None]:
        if payload.idea:
            idea_result = await provider.draft_spec(idea=payload.idea, model_id=payload.model_id)
            idea_prompt = str(idea_result.pop("idea_prompt", "")) or None
            spec = WidgetSpecDraft.model_validate(idea_result)
            async with self.session_factory() as session:
                repository = BoardRepository(session)
                notes = validate_widget_spec(spec)
                stage = await repository.create_staged_spec(
                    widget_id=spec.id,
                    stage="validated" if not notes else "draft",
                    spec=spec.model_dump(mode="json"),
                    scaffold_preview=scaffold_preview(spec),
                    notes=notes,
                )
            return spec, stage.id, idea_prompt

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
            return spec, stage_record.id, None

    async def _serialize_job(self, session: AsyncSession, job_id: str) -> GenerationJobRead:
        repository = GenerationRepository(session)
        job = await repository.get_job(job_id)
        if job is None:
            raise ValueError(f"unknown generation job '{job_id}'")
        artifacts = await repository.list_artifacts(job_id)
        logs = await repository.list_logs(job_id)
        install_target = await self._build_install_target(job.widget_id, job.selected_version)
        diff_preview = await self._build_diff_preview(session=session, job_id=job_id, widget_id=job.widget_id)
        return serialize_job(
            job,
            artifacts=artifacts,
            logs=logs,
            install_target=install_target,
            diff_preview=diff_preview,
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
        ("renderer.tsx", candidate["renderer_source"], ((baseline or {}).get("renderer_source") or "")),
    ]
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
