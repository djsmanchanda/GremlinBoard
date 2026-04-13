from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gremlinboard_api.models.tables import (
    GenerationArtifactRecord,
    GenerationJobLogRecord,
    GenerationJobRecord,
)
from gremlinboard_api.schemas.contracts import (
    GenerationArtifactDiffRead,
    GenerationArtifactFileRead,
    GenerationArtifactRead,
    GenerationJobLogRead,
    GenerationJobRead,
    GenerationJobStatus,
)


class GenerationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def next_artifact_version(self, widget_id: str) -> int:
        result = await self.session.execute(
            select(func.max(GenerationJobRecord.artifact_version)).where(GenerationJobRecord.widget_id == widget_id)
        )
        current = result.scalar_one_or_none()
        return int(current or 0) + 1

    async def create_job(
        self,
        *,
        widget_id: str,
        provider_id: str,
        requested_provider_id: str | None,
        stage_id: str | None,
        idea: str | None,
        artifact_version: int,
        selected_version: str,
        status: GenerationJobStatus = GenerationJobStatus.QUEUED,
        install_blocked: bool = True,
    ) -> GenerationJobRecord:
        record = GenerationJobRecord(
            widget_id=widget_id,
            provider_id=provider_id,
            requested_provider_id=requested_provider_id,
            stage_id=stage_id,
            idea_text=idea,
            artifact_version=artifact_version,
            selected_version=selected_version,
            status=status.value,
            install_blocked=install_blocked,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_job(self, job_id: str) -> GenerationJobRecord | None:
        return await self.session.get(GenerationJobRecord, job_id)

    async def list_jobs(self, *, widget_id: str | None = None, limit: int = 50) -> list[GenerationJobRecord]:
        query = select(GenerationJobRecord).order_by(GenerationJobRecord.created_at.desc()).limit(limit)
        if widget_id is not None:
            query = query.where(GenerationJobRecord.widget_id == widget_id)
        result = await self.session.execute(query)
        return list(result.scalars())

    async def update_job(
        self,
        record: GenerationJobRecord,
        *,
        status: GenerationJobStatus | None = None,
        current_step: str | None = None,
        stage_id: str | None = None,
        provider_id: str | None = None,
        install_blocked: bool | None = None,
        error_message: str | None = None,
        clear_error: bool = False,
        completed_at=None,
    ) -> GenerationJobRecord:
        if status is not None:
            record.status = status.value
        if current_step is not None:
            record.current_step = current_step
        if stage_id is not None:
            record.stage_id = stage_id
        if provider_id is not None:
            record.provider_id = provider_id
        if install_blocked is not None:
            record.install_blocked = install_blocked
        if clear_error:
            record.error_message = None
        elif error_message is not None:
            record.error_message = error_message
        if completed_at is not None:
            record.completed_at = completed_at
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def add_log(
        self,
        *,
        job_id: str,
        level: str,
        step: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> GenerationJobLogRecord:
        record = GenerationJobLogRecord(
            job_id=job_id,
            level=level,
            step=step,
            message=message,
            context_json=json.dumps(context or {}),
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def list_logs(self, job_id: str) -> list[GenerationJobLogRecord]:
        result = await self.session.execute(
            select(GenerationJobLogRecord)
            .where(GenerationJobLogRecord.job_id == job_id)
            .order_by(GenerationJobLogRecord.created_at.asc())
        )
        return list(result.scalars())

    async def add_artifact(
        self,
        *,
        job_id: str,
        widget_id: str,
        artifact_version: int,
        stage: str,
        artifact_type: str,
        payload: dict[str, Any] | None = None,
        content_text: str | None = None,
    ) -> GenerationArtifactRecord:
        record = GenerationArtifactRecord(
            job_id=job_id,
            widget_id=widget_id,
            artifact_version=artifact_version,
            stage=stage,
            artifact_type=artifact_type,
            content_json=json.dumps(payload) if payload is not None else None,
            content_text=content_text,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def list_artifacts(self, job_id: str) -> list[GenerationArtifactRecord]:
        result = await self.session.execute(
            select(GenerationArtifactRecord)
            .where(GenerationArtifactRecord.job_id == job_id)
            .order_by(GenerationArtifactRecord.created_at.asc())
        )
        return list(result.scalars())

    async def get_latest_artifact(
        self,
        *,
        job_id: str,
        stage: str,
        artifact_type: str,
    ) -> GenerationArtifactRecord | None:
        result = await self.session.execute(
            select(GenerationArtifactRecord)
            .where(
                GenerationArtifactRecord.job_id == job_id,
                GenerationArtifactRecord.stage == stage,
                GenerationArtifactRecord.artifact_type == artifact_type,
            )
            .order_by(GenerationArtifactRecord.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_package_artifact_for_widget(
        self,
        *,
        widget_id: str,
        exclude_job_id: str | None = None,
    ) -> GenerationArtifactRecord | None:
        query = (
            select(GenerationArtifactRecord)
            .where(
                GenerationArtifactRecord.widget_id == widget_id,
                GenerationArtifactRecord.stage == "codegen",
                GenerationArtifactRecord.artifact_type == "package",
            )
            .order_by(GenerationArtifactRecord.artifact_version.desc(), GenerationArtifactRecord.created_at.desc())
            .limit(1)
        )
        if exclude_job_id is not None:
            query = query.where(GenerationArtifactRecord.job_id != exclude_job_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()


def decode_artifact_payload(record: GenerationArtifactRecord) -> dict[str, Any]:
    if record.content_json:
        return json.loads(record.content_json)
    if record.content_text is not None:
        return {"content": record.content_text}
    return {}


def serialize_job_log(record: GenerationJobLogRecord) -> GenerationJobLogRead:
    return GenerationJobLogRead(
        id=record.id,
        level=record.level,
        step=record.step,
        message=record.message,
        context=json.loads(record.context_json or "{}"),
        created_at=record.created_at,
    )


def serialize_artifact(record: GenerationArtifactRecord) -> GenerationArtifactRead:
    payload = decode_artifact_payload(record)
    files = [
        GenerationArtifactFileRead(
            path=file_payload["path"],
            language=file_payload["language"],
            content=file_payload["content"],
        )
        for file_payload in payload.get("files", [])
    ]
    return GenerationArtifactRead(
        stage=record.stage,
        artifact_type=record.artifact_type,
        artifact_version=record.artifact_version,
        files=files,
        payload=payload,
        created_at=record.created_at,
    )


def serialize_job(
    record: GenerationJobRecord,
    *,
    artifacts: list[GenerationArtifactRecord],
    logs: list[GenerationJobLogRecord],
    install_target: dict[str, Any] | None = None,
    diff_preview: list[GenerationArtifactDiffRead] | None = None,
) -> GenerationJobRead:
    return GenerationJobRead(
        id=record.id,
        widget_id=record.widget_id,
        stage_id=record.stage_id,
        requested_provider_id=record.requested_provider_id,
        provider_id=record.provider_id,
        status=GenerationJobStatus(record.status),
        current_step=record.current_step,
        idea=record.idea_text,
        install_blocked=record.install_blocked,
        artifact_version=record.artifact_version,
        selected_version=record.selected_version,
        error_message=record.error_message,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
        artifacts=[serialize_artifact(artifact) for artifact in artifacts],
        logs=[serialize_job_log(log) for log in logs],
        install_target=install_target,
        diff_preview=diff_preview or [],
    )
