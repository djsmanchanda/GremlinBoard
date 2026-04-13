from __future__ import annotations

import json
from datetime import datetime, timezone
from difflib import unified_diff
from typing import Any

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
    GenerationArtifactDiffRead,
    GenerationJobCreateRequest,
    GenerationJobRead,
    GenerationJobStatus,
    GenerationPipelinePreviewRead,
    WidgetPackagePayload,
    WidgetPluginInstallRequest,
    WidgetPluginUpdateRequest,
    WidgetSpecDraft,
)
from gremlinboard_api.services.plugin_manager import PluginManagerService
from gremlinboard_api.services.scaffold_generator import WidgetScaffoldGenerator
from gremlinboard_api.specs.pipeline import (
    build_manifest_preview_with_version,
    scaffold_preview,
    validate_widget_spec,
)


class GenerationPipelineService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        plugin_manager: PluginManagerService,
    ) -> None:
        self.session_factory = session_factory
        self.plugin_manager = plugin_manager
        self.scaffold_generator = WidgetScaffoldGenerator()
        self.providers: dict[str, AIProvider] = {
            "codex": CodexProvider(),
            "claude": ClaudeProvider(),
        }

    async def list_providers(self) -> list[AIProviderRead]:
        items: list[AIProviderRead] = []
        for provider in self.providers.values():
            health = await provider.health()
            items.append(
                AIProviderRead(
                    provider_id=provider.provider_id,
                    label=provider.label,
                    status=str(health.get("status", "unknown")),
                    supports_codegen=provider.supports_codegen,
                    supports_review=provider.supports_review,
                    supports_idea_to_spec=provider.supports_idea_to_spec,
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
        provider = await self._select_provider(payload.provider_id, payload.fallback_provider_ids)
        spec, stage_id, idea_prompt = await self._resolve_spec_source(payload=payload, provider=provider)
        artifact_version = await self._next_artifact_version(spec.id)
        selected_version = await self._resolve_version(widget_id=spec.id, requested_version=payload.version)

        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            job = await repository.create_job(
                widget_id=spec.id,
                provider_id=provider.provider_id,
                requested_provider_id=payload.provider_id,
                stage_id=stage_id,
                idea=payload.idea,
                artifact_version=artifact_version,
                selected_version=selected_version,
            )
            await repository.add_log(
                job_id=job.id,
                level="info",
                step="spec",
                message="Generation job created.",
                context={"stage_id": stage_id, "provider_id": provider.provider_id},
            )

        try:
            return await self._execute_job(
                job_id=job.id,
                spec=spec,
                provider=provider,
                idea_prompt=idea_prompt,
            )
        except Exception as exc:
            async with self.session_factory() as session:
                repository = GenerationRepository(session)
                record = await repository.get_job(job.id)
                if record is not None:
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
                        context={"error": str(exc)},
                    )
            raise

    async def approve_job(self, *, job_id: str) -> GenerationJobRead:
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            job = await repository.get_job(job_id)
            if job is None:
                raise ValueError(f"unknown generation job '{job_id}'")
            if job.status != GenerationJobStatus.REVIEW_REQUIRED.value:
                raise ValueError("only review-required jobs can be approved")
            await repository.update_job(
                job,
                status=GenerationJobStatus.APPROVED,
                current_step="approved",
                install_blocked=False,
                clear_error=True,
            )
            await repository.add_log(
                job_id=job.id,
                level="info",
                step="review",
                message="Generation job approved for install.",
                context={},
            )
        return await self.get_job(job_id=job_id)

    async def reject_job(self, *, job_id: str, reason: str) -> GenerationJobRead:
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            job = await repository.get_job(job_id)
            if job is None:
                raise ValueError(f"unknown generation job '{job_id}'")
            if job.status not in {GenerationJobStatus.REVIEW_REQUIRED.value, GenerationJobStatus.APPROVED.value}:
                raise ValueError("only reviewable jobs can be rejected")
            await repository.update_job(
                job,
                status=GenerationJobStatus.REJECTED,
                current_step="rejected",
                install_blocked=True,
                error_message=reason,
            )
            await repository.add_log(
                job_id=job.id,
                level="warning",
                step="review",
                message="Generation job rejected.",
                context={"reason": reason},
            )
        return await self.get_job(job_id=job_id)

    async def install_job(self, *, job_id: str, enabled: bool) -> GenerationJobRead:
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            job = await repository.get_job(job_id)
            if job is None:
                raise ValueError(f"unknown generation job '{job_id}'")
            if job.status != GenerationJobStatus.APPROVED.value:
                raise ValueError("job must be approved before install")
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
            await repository.update_job(
                record,
                status=GenerationJobStatus.INSTALLED,
                current_step="install",
                install_blocked=False,
                clear_error=True,
                completed_at=datetime.now(timezone.utc),
            )
            await repository.add_log(
                job_id=record.id,
                level="info",
                step="install",
                message="Generated widget package installed through the registry.",
                context={"widget_id": record.widget_id, "version": record.selected_version},
            )
        return await self.get_job(job_id=job_id)

    async def _execute_job(
        self,
        *,
        job_id: str,
        spec: WidgetSpecDraft,
        provider: AIProvider,
        idea_prompt: str | None,
    ) -> GenerationJobRead:
        async with self.session_factory() as session:
            repository = GenerationRepository(session)
            job = await repository.get_job(job_id)
            if job is None:
                raise ValueError(f"unknown generation job '{job_id}'")

            await repository.update_job(job, status=GenerationJobStatus.RUNNING, current_step="spec", clear_error=True)
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
                context={"stage_id": job.stage_id},
            )

            scaffold = self.scaffold_generator.generate(
                spec=spec,
                version=job.selected_version,
                artifact_version=job.artifact_version,
            )
            await repository.update_job(job, current_step="scaffold")
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
                context={"file_count": len(scaffold["files"])},
            )

            provider_codegen = await provider.prepare_codegen(
                widget_spec=spec_payload,
                scaffold_files=scaffold["preview"]["files"],
            )
            await repository.update_job(job, current_step="codegen")
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
                context={"artifact_version": job.artifact_version},
            )

            review = await provider.review_package(widget_spec=spec_payload, package=scaffold["package"])
            await repository.update_job(
                job,
                status=GenerationJobStatus.REVIEW_REQUIRED,
                current_step="review",
                install_blocked=True,
                completed_at=datetime.now(timezone.utc),
            )
            await repository.add_artifact(
                job_id=job.id,
                widget_id=job.widget_id,
                artifact_version=job.artifact_version,
                stage="review",
                artifact_type="report",
                payload=review,
            )
            await repository.add_log(
                job_id=job.id,
                level="info",
                step="review",
                message="Review artifact created. Install remains blocked pending approval.",
                context={"provider_id": provider.provider_id},
            )
        return await self.get_job(job_id=job_id)

    async def _resolve_spec_source(
        self,
        *,
        payload: GenerationJobCreateRequest,
        provider: AIProvider,
    ) -> tuple[WidgetSpecDraft, str | None, str | None]:
        if payload.idea:
            idea_result = await provider.draft_spec(idea=payload.idea)
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
        if requested_provider_id is not None:
            chain = [requested_provider_id, *fallback_provider_ids]
        else:
            chain = [*fallback_provider_ids, *self.providers.keys()]
        seen: set[str] = set()
        for provider_id in chain:
            if provider_id in seen:
                continue
            seen.add(provider_id)
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


def _bump_patch_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return version
    major, minor, patch = (int(part) for part in parts)
    return f"{major}.{minor}.{patch + 1}"


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
