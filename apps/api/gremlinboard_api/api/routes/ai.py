from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from gremlinboard_api.schemas.contracts import (
    AIProviderRead,
    GenerationJobCreateRequest,
    GenerationJobInstallRequest,
    GenerationJobRead,
    GenerationJobRejectRequest,
    GenerationPipelinePreviewRead,
    WidgetPluginRead,
    WidgetPluginRollbackRequest,
)


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


@router.get("/generation/jobs", response_model=list[GenerationJobRead])
async def list_generation_jobs(
    request: Request,
    widget_id: str | None = Query(default=None),
) -> list[GenerationJobRead]:
    return await request.app.state.generation_pipeline.list_jobs(widget_id=widget_id)


@router.get("/generation/jobs/{job_id}", response_model=GenerationJobRead)
async def get_generation_job(job_id: str, request: Request) -> GenerationJobRead:
    try:
        return await request.app.state.generation_pipeline.get_job(job_id=job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/generation/jobs", response_model=GenerationJobRead)
async def create_generation_job(
    payload: GenerationJobCreateRequest,
    request: Request,
) -> GenerationJobRead:
    try:
        return await request.app.state.generation_pipeline.create_job(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/generation/jobs/{job_id}/approve", response_model=GenerationJobRead)
async def approve_generation_job(job_id: str, request: Request) -> GenerationJobRead:
    try:
        return await request.app.state.generation_pipeline.approve_job(job_id=job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/generation/jobs/{job_id}/reject", response_model=GenerationJobRead)
async def reject_generation_job(
    job_id: str,
    payload: GenerationJobRejectRequest,
    request: Request,
) -> GenerationJobRead:
    try:
        return await request.app.state.generation_pipeline.reject_job(job_id=job_id, reason=payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/generation/jobs/{job_id}/install", response_model=GenerationJobRead)
async def install_generation_job(
    job_id: str,
    payload: GenerationJobInstallRequest,
    request: Request,
) -> GenerationJobRead:
    try:
        result = await request.app.state.generation_pipeline.install_job(job_id=job_id, enabled=payload.enabled)
        await request.app.state.runtime_manager.restart_widgets_by_widget_id(
            result.widget_id,
            reason="generated widget installed",
        )
        await request.app.state.runtime_manager.publish_board_snapshot()
        await request.app.state.event_bus.publish(
            {"type": "registry.updated", "payload": {"widget_id": result.widget_id}}
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/generation/widgets/{widget_id}/rollback", response_model=WidgetPluginRead)
async def rollback_generated_widget(
    widget_id: str,
    payload: WidgetPluginRollbackRequest,
    request: Request,
) -> WidgetPluginRead:
    try:
        plugin = await request.app.state.plugin_manager.rollback_widget(widget_id, payload.version)
        await request.app.state.runtime_manager.restart_widgets_by_widget_id(
            widget_id,
            reason="generated widget rolled back",
        )
        await request.app.state.event_bus.publish({"type": "registry.updated", "payload": {"widget_id": widget_id}})
        return plugin
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
