from __future__ import annotations

import json
from typing import Any

import httpx

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
        return httpx.Response(200, json=payload)

    exit_code = cli.run(["--mode", "dev", "--json", "runtime", "status"], client_factory=_client_factory(handler))

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == payload


def test_cli_widget_refresh_posts_to_board_action() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"widgets": []})

    exit_code = cli.run(["widgets", "refresh", "widget-1"], client_factory=_client_factory(handler))

    assert exit_code == 0
    assert seen == [("POST", "/api/board/widgets/widget-1/refresh")]


def _client_factory(handler):
    def factory(*, base_url: str, timeout: float) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), base_url=base_url, timeout=timeout)

    return factory
