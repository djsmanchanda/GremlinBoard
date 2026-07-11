from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server.fastmcp import FastMCP
from mcp.types import Tool

from gremlinboard_api.schemas.contracts import EasyGenerationCreateRequest
from gremlinboard_api.services.control_plane import ControlPlaneError


class McpGenerateInput(BaseModel):
    idea: str = Field(min_length=1)
    provider_id: str | None = None
    model_id: str | None = None
    reasoning_effort: str | None = None
    fallback_provider_ids: list[str] = Field(default_factory=list)
    version: str | None = None


class McpJobInput(BaseModel):
    job_id: str = Field(min_length=1)


class McpInstallInput(McpJobInput):
    enabled: bool = True


class McpApprovalInput(BaseModel):
    approval_id: str = Field(min_length=1)
    note: str | None = None


class GremlinBoardMcp(FastMCP):
    """FastMCP adapter that obtains its dynamic catalog from live app services."""

    def __init__(self, service: McpServerService) -> None:
        self._service = service
        super().__init__(
            "GremlinBoard",
            instructions="Local GremlinBoard operator controls. Generated widgets remain review-gated.",
            streamable_http_path="/",
            stateless_http=True,
            json_response=True,
        )

    async def list_tools(self) -> list[Tool]:
        return self._service.tool_definitions()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._service.call_tool(name, arguments)


class McpServerService:
    """Authenticated MCP facade over the existing control and generation services."""

    credential_provider = "mcp"

    def __init__(self) -> None:
        self.app: FastAPI | None = None
        self.server = GremlinBoardMcp(self)
        self._transport_app = self.server.streamable_http_app()

    def attach(self, app: FastAPI) -> None:
        self.app = app

    def asgi_app(self) -> ASGIApp:
        return _AuthenticatedMcpApp(self, self._transport_app)

    @asynccontextmanager
    async def lifespan(self):
        async with self._transport_app.router.lifespan_context(self._transport_app):
            yield

    def tool_definitions(self) -> list[Tool]:
        app = self._require_app()
        control_tools = [
            Tool(name=tool.name, description=tool.description, inputSchema=tool.input_schema)
            for tool in app.state.control_plane.mcp_tools()
        ]
        generation_tools = [
            _tool("widgets.generate", "Create a configured widget generation job.", McpGenerateInput),
            _tool("jobs.status", "Get the current state of one generation job.", McpJobInput),
            _tool("generation.preview", "Get a generation job and its review test-box payload.", McpJobInput),
            _tool("generation.approve", "Approve a completed generation job only when review gates pass.", McpJobInput),
            _tool("generation.install", "Install a generation job only after review approval.", McpInstallInput),
            _tool("approvals.approve", "Approve a pending destructive board-control action.", McpApprovalInput),
        ]
        return control_tools + generation_tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        app = self._require_app()
        if name.startswith("gremlinboard_"):
            response = await app.state.control_plane.call_mcp_tool(
                tool_name=name,
                arguments=arguments,
                user_id=None,
                correlation_id=None,
                causation_id=None,
            )
            return response.model_dump(mode="json")

        if name == "widgets.generate":
            payload = McpGenerateInput.model_validate(arguments)
            job = await app.state.generation_pipeline.create_easy_job(
                EasyGenerationCreateRequest(**payload.model_dump())
            )
            return job.model_dump(mode="json")
        if name == "jobs.status":
            payload = McpJobInput.model_validate(arguments)
            return (await app.state.generation_pipeline.get_job(job_id=payload.job_id)).model_dump(mode="json")
        if name == "generation.preview":
            payload = McpJobInput.model_validate(arguments)
            return (await app.state.generation_pipeline.get_easy_job(job_id=payload.job_id)).model_dump(mode="json")
        if name == "generation.approve":
            payload = McpJobInput.model_validate(arguments)
            return (await app.state.generation_pipeline.approve_job(job_id=payload.job_id)).model_dump(mode="json")
        if name == "generation.install":
            payload = McpInstallInput.model_validate(arguments)
            result = await app.state.generation_pipeline.install_job(job_id=payload.job_id, enabled=payload.enabled)
            await app.state.runtime_manager.restart_widgets_by_widget_id(
                result.widget_id,
                reason="generated widget installed through MCP",
            )
            await app.state.runtime_manager.publish_board_snapshot()
            await app.state.event_bus.publish({"type": "registry.updated", "payload": {"widget_id": result.widget_id}})
            return result.model_dump(mode="json")
        if name == "approvals.approve":
            payload = McpApprovalInput.model_validate(arguments)
            response = await app.state.control_plane.approve(
                payload.approval_id,
                source="mcp",
                note=payload.note,
            )
            return response.model_dump(mode="json")
        raise ControlPlaneError(f"unknown MCP tool '{name}'")

    async def authenticate(self, headers: Headers) -> JSONResponse | None:
        app = self._require_app()
        credentials = await app.state.system_settings.list_credential_secrets_by_provider()
        expected_token = credentials.get(self.credential_provider)
        if not expected_token:
            return JSONResponse(
                status_code=503,
                content={"detail": "MCP is unavailable until an 'mcp' system credential is configured."},
            )
        scheme, _, token = headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token or not hmac.compare_digest(token, expected_token):
            return JSONResponse(status_code=401, content={"detail": "valid MCP bearer authentication is required"})
        return None

    def _require_app(self) -> FastAPI:
        if self.app is None:
            raise RuntimeError("MCP server is not attached to a FastAPI application")
        return self.app


class _AuthenticatedMcpApp:
    def __init__(self, service: McpServerService, app: ASGIApp) -> None:
        self.service = service
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            rejection = await self.service.authenticate(Headers(scope=scope))
            if rejection is not None:
                await rejection(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _tool(name: str, description: str, model: type[BaseModel]) -> Tool:
    return Tool(name=name, description=description, inputSchema=model.model_json_schema())