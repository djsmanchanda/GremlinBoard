from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from gremlinboard_api.schemas.control import (
    ControlActionDefinitionRead,
    ControlActionRequest,
    ControlActionResponse,
    ControlApprovalDecisionRequest,
    ControlApprovalListRead,
    ControlMcpToolCallRequest,
    ControlMcpToolRead,
)
from gremlinboard_api.services.control_plane import ControlApprovalNotFound, ControlPlaneError


router = APIRouter(prefix="/control", tags=["control"])


@router.get("/actions", response_model=list[ControlActionDefinitionRead])
async def list_control_actions(request: Request) -> list[ControlActionDefinitionRead]:
    return request.app.state.control_plane.action_definitions()


@router.post("/actions/{action_id}", response_model=ControlActionResponse)
async def run_control_action(
    action_id: str,
    payload: ControlActionRequest,
    request: Request,
) -> ControlActionResponse:
    try:
        return await request.app.state.control_plane.execute_action(
            action_id,
            params=payload.params,
            source=payload.source,
            user_id=request.state.auth_context.user.id,
            correlation_id=payload.correlation_id,
            causation_id=payload.causation_id,
        )
    except ControlPlaneError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/approvals", response_model=ControlApprovalListRead)
async def list_control_approvals(request: Request) -> ControlApprovalListRead:
    return ControlApprovalListRead(approvals=request.app.state.control_plane.list_approvals())


@router.post("/approvals/{approval_id}/approve", response_model=ControlActionResponse)
async def approve_control_action(
    approval_id: str,
    payload: ControlApprovalDecisionRequest,
    request: Request,
) -> ControlActionResponse:
    try:
        return await request.app.state.control_plane.approve(approval_id, source=payload.source, note=payload.note)
    except ControlApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ControlPlaneError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/approvals/{approval_id}/reject", response_model=ControlActionResponse)
async def reject_control_action(
    approval_id: str,
    payload: ControlApprovalDecisionRequest,
    request: Request,
) -> ControlActionResponse:
    try:
        return await request.app.state.control_plane.reject(approval_id, source=payload.source, note=payload.note)
    except ControlApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ControlPlaneError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/mcp/tools", response_model=list[ControlMcpToolRead])
async def list_control_mcp_tools(request: Request) -> list[ControlMcpToolRead]:
    return request.app.state.control_plane.mcp_tools()


@router.post("/mcp/call", response_model=ControlActionResponse)
async def call_control_mcp_tool(
    payload: ControlMcpToolCallRequest,
    request: Request,
) -> ControlActionResponse:
    try:
        return await request.app.state.control_plane.call_mcp_tool(
            tool_name=payload.tool_name,
            arguments=payload.arguments,
            user_id=request.state.auth_context.user.id,
            correlation_id=payload.correlation_id,
            causation_id=payload.causation_id,
        )
    except ControlPlaneError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
