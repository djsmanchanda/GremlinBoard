from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from gremlinboard_api.db import get_session
from gremlinboard_api.repositories.board import BoardRepository
from gremlinboard_api.schemas.contracts import (
    SpecDocumentValidateRequest,
    WidgetSpecDraft,
    WidgetSpecValidationRead,
)
from gremlinboard_api.specs.pipeline import (
    build_manifest_preview,
    parse_and_validate_spec,
    scaffold_preview,
    validate_widget_spec,
)


router = APIRouter(prefix="/specs", tags=["specs"])


@router.post("/validate", response_model=WidgetSpecValidationRead)
async def validate_spec(
    payload: WidgetSpecDraft,
    session: AsyncSession = Depends(get_session),
) -> WidgetSpecValidationRead:
    notes = validate_widget_spec(payload)
    manifest = build_manifest_preview(payload)
    preview = scaffold_preview(payload)
    repository = BoardRepository(session)
    record = await repository.create_staged_spec(
        widget_id=payload.id,
        stage="validated" if not notes else "draft",
        spec=payload.model_dump(mode="json"),
        scaffold_preview=preview,
        notes=notes,
    )
    return WidgetSpecValidationRead(
        stage_id=record.id,
        stage=record.stage,
        valid=not notes,
        notes=notes,
        normalized_spec=payload.model_dump(mode="json"),
        manifest_preview=manifest,
        scaffold_preview=preview,
        errors=[],
    )


@router.post("/preview", response_model=WidgetSpecValidationRead)
async def preview_spec_document(
    payload: SpecDocumentValidateRequest,
    session: AsyncSession = Depends(get_session),
) -> WidgetSpecValidationRead:
    spec, errors = parse_and_validate_spec(content=payload.content, format=payload.format)
    if spec is None:
        return WidgetSpecValidationRead(
            stage_id="preview-error",
            stage="draft",
            valid=False,
            notes=[],
            normalized_spec=None,
            manifest_preview={},
            scaffold_preview={"files": [], "review_required": True, "install_blocked": True},
            errors=errors,
        )
    notes = validate_widget_spec(spec)
    manifest = build_manifest_preview(spec)
    preview = scaffold_preview(spec)
    repository = BoardRepository(session)
    record = await repository.create_staged_spec(
        widget_id=spec.id,
        stage="validated" if not notes else "draft",
        spec=spec.model_dump(mode="json"),
        scaffold_preview=preview,
        notes=notes,
    )
    return WidgetSpecValidationRead(
        stage_id=record.id,
        stage=record.stage,
        valid=not notes and not errors,
        notes=notes,
        normalized_spec=spec.model_dump(mode="json"),
        manifest_preview=manifest,
        scaffold_preview=preview,
        errors=errors,
    )
