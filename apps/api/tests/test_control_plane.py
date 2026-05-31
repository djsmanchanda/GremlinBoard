from __future__ import annotations

import pytest

from gremlinboard_api.schemas.contracts import LifecycleState

from .runtime_test_harness import RuntimeTestHarness, build_widget_package, write_widget_package


CONTROL_WIDGET_BACKEND = """
from __future__ import annotations

from gremlinboard_api.runtime.base import BaseWidgetService


class ControlWidgetService(BaseWidgetService):
    async def start(self) -> None:
        self.state = await self.get_state()

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        return {"status": "running", "expired": False}

    async def get_state(self) -> dict[str, object]:
        return {"provider": self.config.get("provider", "local"), "instance_id": self.instance_id}
""".strip()


async def _write_and_sync_control_widget(harness: RuntimeTestHarness) -> None:
    package = build_widget_package(
        package_name=harness.package_name,
        widget_id="control_widget",
        version="1.0.0",
        class_name="ControlWidgetService",
        backend_source=CONTROL_WIDGET_BACKEND,
        config_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"provider": {"type": "string", "default": "local"}},
            "additionalProperties": False,
        },
        description="Control plane test widget.",
        allowed_sizes=["1x1", "2x2", "4x2"],
    )
    write_widget_package(harness.widgets_dir, "control_widget", package)
    harness.registry.load()
    await harness.plugin_manager.sync_with_filesystem()


@pytest.mark.asyncio
async def test_control_actions_expose_mcp_tools_and_reject_unknown_actions() -> None:
    harness = await RuntimeTestHarness.create()
    try:
        actions_response = await harness.client.get("/api/control/actions")
        assert actions_response.status_code == 200
        actions = {action["action_id"]: action for action in actions_response.json()}

        assert actions["widgets.remove"]["approval_required"] is True
        assert actions["widgets.remove"]["destructive"] is True
        assert actions["widgets.add"]["input_schema"]["properties"]["widget_id"]["minLength"] == 1

        tools_response = await harness.client.get("/api/control/mcp/tools")
        assert tools_response.status_code == 200
        tools = {tool["name"]: tool for tool in tools_response.json()}
        assert tools["gremlinboard_widgets_list"]["action_id"] == "widgets.list"
        assert tools["gremlinboard_widgets_remove"]["approval_required"] is True

        unknown_response = await harness.client.post("/api/control/actions/shell.exec", json={"params": {}})
        assert unknown_response.status_code == 400
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_control_widget_lifecycle_uses_approval_gate_and_emits_audit_events() -> None:
    harness = await RuntimeTestHarness.create()
    try:
        await _write_and_sync_control_widget(harness)

        add_response = await harness.client.post(
            "/api/control/actions/widgets.add",
            json={
                "source": "cli",
                "correlation_id": "ctrl-test-1",
                "params": {
                    "widget_id": "control_widget",
                    "title": "Control Widget",
                    "size": "2x2",
                    "config": {"provider": "local"},
                },
            },
        )
        assert add_response.status_code == 200
        added = add_response.json()
        assert added["status"] == "completed"
        assert added["correlation_id"] == "ctrl-test-1"
        widget_id = added["payload"]["id"]

        running = await harness.wait_for_widget(
            widget_id,
            predicate=lambda widget: widget.lifecycle_state == LifecycleState.RUNNING,
        )
        assert running.config == {"provider": "local"}

        resize_response = await harness.client.post(
            "/api/control/actions/widgets.resize",
            json={"source": "mcp", "params": {"widget_instance_id": widget_id, "size": "4x2"}},
        )
        assert resize_response.status_code == 200
        assert resize_response.json()["payload"]["size"] == "4x2"

        pause_response = await harness.client.post(
            "/api/control/actions/widgets.pause",
            json={"source": "cli", "params": {"widget_instance_id": widget_id}},
        )
        assert pause_response.status_code == 200
        paused = await harness.wait_for_widget(
            widget_id,
            predicate=lambda widget: widget.lifecycle_state == LifecycleState.PAUSED,
        )
        assert paused.status_message == "cli requested pause"

        resume_response = await harness.client.post(
            "/api/control/actions/widgets.resume",
            json={"source": "cli", "params": {"widget_instance_id": widget_id}},
        )
        assert resume_response.status_code == 200
        await harness.wait_for_widget(
            widget_id,
            predicate=lambda widget: widget.lifecycle_state == LifecycleState.RUNNING,
        )

        remove_response = await harness.client.post(
            "/api/control/actions/widgets.remove",
            json={"source": "mcp", "params": {"widget_instance_id": widget_id}},
        )
        assert remove_response.status_code == 200
        remove_payload = remove_response.json()
        assert remove_payload["status"] == "approval_required"
        approval_id = remove_payload["approval"]["id"]

        board_before_approval = await harness.client.get("/api/board")
        assert [widget["id"] for widget in board_before_approval.json()["widgets"]] == [widget_id]

        approve_response = await harness.client.post(
            f"/api/control/approvals/{approval_id}/approve",
            json={"source": "cli", "note": "operator approved test removal"},
        )
        assert approve_response.status_code == 200
        assert approve_response.json()["status"] == "completed"

        board_after_approval = await harness.client.get("/api/board")
        assert board_after_approval.json()["widgets"] == []

        audit_log = await harness.wait_for_log(
            predicate=lambda log: log.event == "operator.control.completed"
            and log.context["correlation_id"] == "ctrl-test-1"
        )
        assert audit_log.context["payload"]["action_id"] == "widgets.add"

        approval_log = await harness.wait_for_log(
            predicate=lambda log: log.event == "operator.control.approval_required"
            and log.context["payload"]["id"] == approval_id
        )
        assert approval_log.level == "warning"
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_control_mcp_calls_same_handlers_as_http_actions() -> None:
    harness = await RuntimeTestHarness.create()
    try:
        response = await harness.client.post(
            "/api/control/mcp/call",
            json={
                "tool_name": "gremlinboard_runtime_status",
                "arguments": {},
                "correlation_id": "ctrl-mcp-1",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["action_id"] == "runtime.status"
        assert payload["status"] == "completed"
        assert payload["payload"]["active_runners"] == 0
        assert payload["correlation_id"] == "ctrl-mcp-1"

        unknown = await harness.client.post(
            "/api/control/mcp/call",
            json={"tool_name": "gremlinboard_shell_exec", "arguments": {}},
        )
        assert unknown.status_code == 400
    finally:
        await harness.close()
