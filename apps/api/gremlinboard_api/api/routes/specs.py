from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from gremlinboard_api.db import get_session
from gremlinboard_api.repositories.board import BoardRepository
from gremlinboard_api.schemas.contracts import WidgetSpecDraft, WidgetSpecValidationRead
from gremlinboard_api.specs.pipeline import scaffold_preview, validate_widget_spec


router = APIRouter(prefix="/specs", tags=["specs"])


@router.post("/validate", response_model=WidgetSpecValidationRead)
async def validate_spec(
    payload: WidgetSpecDraft,
    session: AsyncSession = Depends(get_session),
) -> WidgetSpecValidationRead:
    notes = validate_widget_spec(payload)
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
        scaffold_preview=preview,
    )
