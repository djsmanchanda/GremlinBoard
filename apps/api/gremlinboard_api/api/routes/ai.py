from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from gremlinboard_api.schemas.contracts import AIProviderRead, GenerationPipelinePreviewRead


router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/providers", response_model=list[AIProviderRead])
async def list_providers(request: Request) -> list[AIProviderRead]:
    return await request.app.state.generation_pipeline.list_providers()


@router.get("/generation/preview", response_model=GenerationPipelinePreviewRead)
async def generation_preview(
    request: Request,
    stage_id: str = Query(...),
    provider_id: str = Query(...),
) -> GenerationPipelinePreviewRead:
    try:
        return await request.app.state.generation_pipeline.preview_generation(
            provider_id=provider_id,
            stage_id=stage_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
