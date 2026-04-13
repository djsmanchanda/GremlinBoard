from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from gremlinboard_api.schemas.contracts import (
    ApiCredentialRead,
    ApiCredentialUpsertRequest,
    AuthContextRead,
    SystemSettingsRead,
    SystemSettingsUpdateRequest,
)


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/context", response_model=AuthContextRead)
async def get_context(request: Request) -> AuthContextRead:
    return request.state.auth_context


@router.get("/settings", response_model=SystemSettingsRead)
async def get_settings(request: Request) -> SystemSettingsRead:
    return await request.app.state.system_settings.read()


@router.put("/settings", response_model=SystemSettingsRead)
async def update_settings(
    payload: SystemSettingsUpdateRequest,
    request: Request,
) -> SystemSettingsRead:
    settings = await request.app.state.system_settings.update(
        payload,
        user_id=request.state.auth_context.user.id,
    )
    request.app.state.runtime_manager.update_monitor_interval(settings.runtime.monitor_interval_seconds)
    return settings


@router.get("/credentials", response_model=list[ApiCredentialRead])
async def list_credentials(request: Request) -> list[ApiCredentialRead]:
    return await request.app.state.system_settings.list_credentials()


@router.put("/credentials", response_model=ApiCredentialRead)
async def create_credential(
    payload: ApiCredentialUpsertRequest,
    request: Request,
) -> ApiCredentialRead:
    return await request.app.state.system_settings.upsert_credential(
        payload,
        credential_id=None,
        user_id=request.state.auth_context.user.id,
    )


@router.put("/credentials/{credential_id}", response_model=ApiCredentialRead)
async def update_credential(
    credential_id: str,
    payload: ApiCredentialUpsertRequest,
    request: Request,
) -> ApiCredentialRead:
    return await request.app.state.system_settings.upsert_credential(
        payload,
        credential_id=credential_id,
        user_id=request.state.auth_context.user.id,
    )


@router.delete("/credentials/{credential_id}")
async def delete_credential(credential_id: str, request: Request) -> dict[str, str]:
    try:
        await request.app.state.system_settings.delete_credential(credential_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted"}
