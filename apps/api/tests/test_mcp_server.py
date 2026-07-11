from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from httpx import ASGITransport, AsyncClient

pytest.importorskip("mcp")

from gremlinboard_api.config import settings
from gremlinboard_api.schemas.contracts import ApiCredentialUpsertRequest
from gremlinboard_api.services.mcp_server import McpServerService

from .runtime_test_harness import RuntimeTestHarness, build_persistent_widget_package


@pytest.mark.asyncio
async def test_mcp_catalog_auth_and_review_gates_use_existing_services() -> None:
    package = build_persistent_widget_package(
        package_name="widgets",
        widget_id="mcp_control_widget",
        version="1.0.0",
    )
    harness = await RuntimeTestHarness.create(startup_packages=[package])
    try:
        service = McpServerService()
        service.attach(harness.app)

        tools = {tool.name: tool for tool in await service.server.list_tools()}
        assert tools["gremlinboard_runtime_status"].inputSchema == {
            tool.name: tool for tool in harness.control_plane.mcp_tools()
        }["gremlinboard_runtime_status"].input_schema
        assert {
            "widgets.generate",
            "jobs.status",
            "generation.preview",
            "generation.approve",
            "generation.install",
            "approvals.approve",
        }.issubset(tools)

        async with AsyncClient(transport=ASGITransport(app=service.asgi_app()), base_url="http://mcp") as client:
            unavailable = await client.post("/", json={})
        assert unavailable.status_code == 503
        await harness.settings_service.upsert_credential(
            payload=ApiCredentialUpsertRequest(provider="mcp", label="local-token", value="test-mcp-token"),
            credential_id=None,
            user_id=settings.default_user_id,
        )
        async with AsyncClient(transport=ASGITransport(app=service.asgi_app()), base_url="http://mcp") as client:
            unauthorized = await client.post("/", json={})
        assert unauthorized.status_code == 401

        status = await service.server.call_tool("gremlinboard_runtime_status", {})
        assert status["action_id"] == "runtime.status"
        assert status["status"] == "completed"

        added = await service.server.call_tool(
            "gremlinboard_widgets_add",
            {
                "widget_id": "mcp_control_widget",
                "title": "MCP Control Widget",
                "size": "2x2",
                "config": {"notes": []},
            },
        )
        approval = await service.server.call_tool(
            "gremlinboard_widgets_remove",
            {"widget_instance_id": added["payload"]["id"]},
        )
        assert approval["status"] == "approval_required"
        completed = await service.server.call_tool(
            "approvals.approve",
            {"approval_id": approval["approval"]["id"], "note": "test approval"},
        )
        assert completed["status"] == "completed"

        harness.generation_pipeline.create_easy_job = AsyncMock(
            return_value=Mock(model_dump=lambda **_: {"job": {"id": "mcp-job"}, "test_box": None})
        )
        harness.generation_pipeline.get_job = AsyncMock(
            return_value=Mock(model_dump=lambda **_: {"id": "mcp-job", "status": "completed"})
        )
        harness.generation_pipeline.install_job = AsyncMock(side_effect=ValueError("job must pass review before install"))
        generated = await service.server.call_tool(
            "widgets.generate",
            {"idea": "Build a small offline MCP status widget with a health summary."},
        )
        job_id = generated["job"]["id"]
        job = await service.server.call_tool("jobs.status", {"job_id": job_id})
        assert job["id"] == job_id
        with pytest.raises(ValueError, match="pass review"):
            await service.server.call_tool("generation.install", {"job_id": job_id})
        harness.generation_pipeline.create_easy_job.assert_awaited_once()
        harness.generation_pipeline.install_job.assert_awaited_once_with(job_id="mcp-job", enabled=True)
    finally:
        await harness.close()