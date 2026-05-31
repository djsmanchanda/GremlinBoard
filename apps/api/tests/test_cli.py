from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from gremlinboard_api import cli


def test_cli_status_uses_stable_api_default(capsys) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={"status": "ok", "registry_size": 3, "active_runners": 2},
        )

    exit_code = cli.run(["status"], client_factory=_client_factory(handler))

    assert exit_code == 0
    assert seen == ["http://127.0.0.1:2555/api/health"]
    assert "GremlinBoard API ok: registry=3 active_runners=2" in capsys.readouterr().out


def test_cli_runtime_status_can_emit_json(capsys) -> None:
    payload: dict[str, Any] = {
        "state": "idle",
        "active_runners": 0,
        "websocket_subscribers": 0,
        "monitor_cadence_seconds": 30,
        "provider_degradation": [],
        "queue_depth": 0,
        "registry_size": 1,
        "widgets_total": 0,
        "runners": [],
        "startup_recovery": {
            "recovered_widgets": 0,
            "skipped_widgets": 0,
            "orphan_widgets": 0,
            "registry_size": 1,
            "checked_at": "2026-05-20T00:00:00Z",
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://127.0.0.1:2556/api/runtime/status"
        assert request.headers["x-gremlin-presence-source"] == "cli"
        return httpx.Response(200, json=payload)

    exit_code = cli.run(["--mode", "dev", "--json", "runtime", "status"], client_factory=_client_factory(handler))

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == payload


def test_cli_runtime_suspend_posts_operator_command(capsys) -> None:
    seen: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers["x-gremlin-presence-source"]))
        return httpx.Response(
            200,
            json={
                "state": "suspended",
                "active_sources": [],
                "active_websocket_count": 0,
                "recent_interaction_at": None,
                "idle_after_seconds": 90,
                "suspended": True,
                "degraded": False,
                "reason": "cli requested suspend",
                "updated_at": "2026-05-24T00:00:00Z",
            },
        )

    exit_code = cli.run(["runtime", "suspend"], client_factory=_client_factory(handler))

    assert exit_code == 0
    assert seen == [("POST", "/api/runtime/suspend", "cli")]
    assert "Runtime suspended: reason=cli requested suspend" in capsys.readouterr().out


def test_cli_widget_refresh_posts_to_board_action() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"widgets": []})

    exit_code = cli.run(["widgets", "refresh", "widget-1"], client_factory=_client_factory(handler))

    assert exit_code == 0
    assert seen == [("POST", "/api/board/widgets/widget-1/refresh")]


def test_cli_control_widget_remove_uses_typed_control_action(capsys) -> None:
    seen: list[tuple[str, str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(
            200,
            json={
                "action_id": "widgets.remove",
                "status": "approval_required",
                "message": "approval required before running widgets.remove",
                "payload": None,
                "correlation_id": "ctrl-1",
                "causation_id": None,
                "event_id": "approval-1",
                "approval": {
                    "id": "approval-1",
                    "action_id": "widgets.remove",
                    "params": {"widget_instance_id": "widget-1"},
                    "source": "cli",
                    "reason": "widgets.remove is destructive and requires approval",
                    "correlation_id": "ctrl-1",
                    "causation_id": None,
                    "requested_at": "2026-05-28T00:00:00Z",
                    "status": "pending",
                    "resolved_at": None,
                    "resolution_note": None,
                },
            },
        )

    exit_code = cli.run(["control", "widgets", "remove", "widget-1"], client_factory=_client_factory(handler))

    assert exit_code == 0
    assert seen == [
        (
            "POST",
            "/api/control/actions/widgets.remove",
            {"source": "cli", "params": {"widget_instance_id": "widget-1"}},
        )
    ]
    out = capsys.readouterr().out
    assert "widgets.remove: approval_required (ctrl-1)" in out
    assert "Approval approval-1: pending" in out


def test_cli_control_runtime_status_uses_dev_control_action() -> None:
    seen: list[tuple[str, str, dict[str, Any], str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.method,
                str(request.url),
                json.loads(request.content),
                request.headers["x-gremlin-presence-source"],
            )
        )
        return httpx.Response(
            200,
            json={
                "action_id": "runtime.status",
                "status": "completed",
                "message": "runtime.status completed",
                "payload": {"active_runners": 0},
                "correlation_id": "ctrl-2",
                "causation_id": None,
                "event_id": "event-1",
                "approval": None,
            },
        )

    exit_code = cli.run(["--mode", "dev", "control", "runtime", "status"], client_factory=_client_factory(handler))

    assert exit_code == 0
    assert seen == [
        (
            "POST",
            "http://127.0.0.1:2556/api/control/actions/runtime.status",
            {"source": "cli", "params": {}},
            "cli",
        )
    ]


def test_cli_control_approval_approve_posts_decision() -> None:
    seen: list[tuple[str, str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(
            200,
            json={
                "action_id": "widgets.remove",
                "status": "completed",
                "message": "widgets.remove completed",
                "payload": {"widgets": []},
                "correlation_id": "ctrl-3",
                "causation_id": "approval-1",
                "event_id": "event-2",
                "approval": None,
            },
        )

    exit_code = cli.run(
        ["control", "approvals", "approve", "approval-1", "--note", "ok"],
        client_factory=_client_factory(handler),
    )

    assert exit_code == 0
    assert seen == [("POST", "/api/control/approvals/approval-1/approve", {"source": "cli", "note": "ok"})]


def test_gb_widgets_list_uses_typed_control_plane_and_renders_table(capsys) -> None:
    seen: list[tuple[str, str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(
            200,
            json={
                "action_id": "widgets.list",
                "status": "completed",
                "message": "widgets.list completed",
                "payload": [
                    {
                        "id": "widget-1",
                        "widget_id": "news",
                        "title": "News Radar",
                        "size": "4x2",
                        "lifecycle_state": "running",
                        "restart_count": 0,
                    }
                ],
                "correlation_id": "ctrl-widgets",
                "causation_id": None,
                "event_id": "event-widgets",
                "approval": None,
            },
        )

    exit_code = cli.run(["widgets", "list"], prog="gb", client_factory=_client_factory(handler))

    assert exit_code == 0
    assert seen == [("POST", "/api/control/actions/widgets.list", {"source": "cli", "params": {}})]
    output = capsys.readouterr().out
    assert "Widgets (1)" in output
    assert "News Radar" in output
    assert "running" in output


def test_gb_runtime_status_uses_typed_control_plane_and_renders_summary(capsys) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/control/actions/runtime.status"
        return httpx.Response(
            200,
            json={
                "action_id": "runtime.status",
                "status": "completed",
                "message": "runtime.status completed",
                "payload": {
                    "state": "active",
                    "active_runners": 2,
                    "websocket_subscribers": 1,
                    "monitor_cadence_seconds": 30,
                    "queue_depth": 0,
                    "dropped_event_count": 0,
                    "registry_size": 5,
                    "runners": [],
                    "agents": {"active_agents": 1},
                },
                "correlation_id": "ctrl-runtime",
                "causation_id": None,
                "event_id": "event-runtime",
                "approval": None,
            },
        )

    exit_code = cli.run(["runtime", "status"], prog="gb", client_factory=_client_factory(handler))

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Runtime Summary" in output
    assert "Active runners" in output
    assert "2" in output


def test_gb_dev_runtime_status_defaults_to_dev_control_plane() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "action_id": "runtime.status",
                "status": "completed",
                "message": "runtime.status completed",
                "payload": {
                    "state": "idle",
                    "active_runners": 0,
                    "websocket_subscribers": 0,
                    "monitor_cadence_seconds": 30,
                    "queue_depth": 0,
                    "dropped_event_count": 0,
                    "registry_size": 0,
                    "runners": [],
                    "agents": {"active_agents": 0},
                },
                "correlation_id": "ctrl-runtime-dev",
                "causation_id": None,
                "event_id": "event-runtime-dev",
                "approval": None,
            },
        )

    exit_code = cli.run(["runtime", "status"], prog="gb_dev", client_factory=_client_factory(handler))

    assert exit_code == 0
    assert seen == ["http://127.0.0.1:2556/api/control/actions/runtime.status"]


def test_gb_json_mode_remains_machine_readable(capsys) -> None:
    payload = {
        "action_id": "agents.list",
        "status": "completed",
        "message": "agents.list completed",
        "payload": [],
        "correlation_id": "ctrl-agents",
        "causation_id": None,
        "event_id": "event-agents",
        "approval": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/control/actions/agents.list"
        return httpx.Response(200, json=payload)

    exit_code = cli.run(["--json", "agents", "list"], prog="gb", client_factory=_client_factory(handler))

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == payload


def test_gb_devtools_reads_existing_snapshot_route(capsys) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/devtools/snapshot"
        return httpx.Response(
            200,
            json={
                "runtime": {"state": "idle"},
                "queues": {"health": "ok", "event_bus_queue_depth": 0},
                "replay": {"history_size": 4},
                "websocket": {"subscriber_count": 0},
                "providers": {"degradation": []},
                "pressure": {
                    "replay_pressure": "ok",
                    "subscriber_pressure": "ok",
                    "provider_pressure": "ok",
                },
            },
        )

    exit_code = cli.run(["devtools"], prog="gb", client_factory=_client_factory(handler))

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Devtools" in output
    assert "Diagnostics" in output


def test_gb_help_and_version_are_operator_focused(capsys) -> None:
    with pytest.raises(SystemExit) as help_exit:
        cli.run(["--help"], prog="gb")
    assert help_exit.value.code == 0
    help_output = capsys.readouterr().out
    assert "GremlinBoard local operator control plane." in help_output
    assert "Operator commands:" in help_output
    assert "Compatibility commands:" in help_output

    with pytest.raises(SystemExit) as version_exit:
        cli.run(["--version"], prog="gb")
    assert version_exit.value.code == 0
    assert capsys.readouterr().out == "GremlinBoard version: 0.1.0\ngb CLI version: 0.1.0\n"


@pytest.mark.parametrize("prog", ["gremlinboard", "gb", "gb_dev"])
def test_cli_version_reports_board_and_invoking_cli_versions(capsys, prog: str) -> None:
    with pytest.raises(SystemExit) as version_exit:
        cli.run(["-v"], prog=prog)

    assert version_exit.value.code == 0
    assert capsys.readouterr().out == f"GremlinBoard version: 0.1.0\n{prog} CLI version: 0.1.0\n"


@pytest.mark.parametrize(
    ("prog", "argv", "launcher_args"),
    [
        ("gb", ["kill"], ["-StopMode", "stable"]),
        ("gb_dev", ["kill"], ["-StopMode", "dev"]),
        ("gb", ["kill", "--all"], ["-StopAll"]),
        ("gb_dev", ["kill", "--all"], ["-StopAll"]),
        ("gremlinboard", ["stop"], ["-StopAll"]),
    ],
)
def test_cli_kill_and_legacy_stop_use_launcher_scope(
    monkeypatch,
    prog: str,
    argv: list[str],
    launcher_args: list[str],
) -> None:
    seen: list[dict[str, Any]] = []

    monkeypatch.setattr(cli.platform, "system", lambda: "Windows")
    monkeypatch.setattr(cli, "_launcher_path", lambda: Path("scripts/gremlinboard-tray.ps1"))
    monkeypatch.setattr(cli, "_repo_root", lambda: Path("."))

    def run_process(command: list[str], *, cwd: str, check: bool):
        seen.append({"command": command, "cwd": cwd, "check": check})
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(cli.subprocess, "run", run_process)

    exit_code = cli.run(argv, prog=prog)

    assert exit_code == 0
    assert seen == [
        {
            "command": [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                "scripts\\gremlinboard-tray.ps1",
                *launcher_args,
            ],
            "cwd": ".",
            "check": False,
        }
    ]


def _client_factory(handler):
    def factory(*, base_url: str, timeout: float) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), base_url=base_url, timeout=timeout)

    return factory
