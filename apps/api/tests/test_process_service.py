from __future__ import annotations

import asyncio
import json
import shutil
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from gremlinboard_api.registry.loader import load_registry
from gremlinboard_api.runtime.process_service import ProcessServiceError, ProcessWidgetService
from gremlinboard_api.schemas.contracts import WidgetManifest


@pytest.fixture
def workspace_tmp() -> Iterator[Path]:
    root = Path("data") / f"process-service-test-{uuid4().hex}"
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


CHILD_SCRIPT = r'''
from __future__ import annotations

import json
import sys
import time

mode = sys.argv[1]
config = {}
started = False


def respond(request_id, *, result=None, error=None):
    payload = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    print(json.dumps(payload), flush=True)


for line in sys.stdin:
    request = json.loads(line)
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    if method == "start":
        started = True
        config = dict(params.get("config") or {})
        respond(request_id, result={"started": True})
    elif method == "stop":
        if mode == "hang_stop":
            time.sleep(30)
        respond(request_id, result={"stopped": True})
        break
    elif method == "health":
        respond(request_id, result={"status": "running", "healthy": True, "started": started})
    elif method == "get_state":
        if mode == "timeout_get_state":
            time.sleep(30)
        if mode == "crash_get_state":
            sys.exit(7)
        respond(request_id, result={"started": started, "config": config})
    elif method == "refresh":
        respond(request_id, result={"refreshed": True, "force": bool(params.get("force"))})
    elif method == "set_config":
        config = dict(params.get("config") or {})
        respond(request_id, result={"configured": True})
    else:
        respond(request_id, error={"code": -32601, "message": "method not found"})
'''


def _write_child(workspace_tmp: Path) -> Path:
    script = workspace_tmp / "jsonrpc_child.py"
    script.write_text(textwrap.dedent(CHILD_SCRIPT).strip() + "\n", encoding="utf-8")
    return script


def _manifest(command: list[str], runtime_policy: dict[str, int] | None = None) -> WidgetManifest:
    return WidgetManifest.model_validate(
        {
            "id": "process_widget",
            "version": "1.0.0",
            "name": "Process Widget",
            "category": "test",
            "description": "Process service test widget",
            "min_size": "2x2",
            "preferred_size": "2x2",
            "allowed_sizes": ["2x2"],
            "refresh_policy": {"mode": "manual", "interval_seconds": 0},
            "lifecycle_policy": {"stateful": True, "expires": False, "default_ttl_seconds": None},
            "runtime_policy": {
                "start_timeout_seconds": 2,
                "refresh_timeout_seconds": 1,
                "heartbeat_timeout_seconds": 10,
                "max_retries": 0,
                "retry_backoff_seconds": 1,
                "stale_after_seconds": 30,
                **(runtime_policy or {}),
            },
            "permissions": [],
            "renderer": {
                "kind": "module",
                "target": "react",
                "module": "@widgets/process_widget/renderer",
                "export_name": "ProcessWidgetRenderer",
            },
            "service": {"kind": "process", "command": command},
            "config_schema": "config.schema.json",
        }
    )


def _service(workspace_tmp: Path, mode: str, *, runtime_policy: dict[str, int] | None = None) -> ProcessWidgetService:
    script = _write_child(workspace_tmp)
    manifest = _manifest([sys.executable, str(script.resolve()), mode], runtime_policy=runtime_policy)
    return ProcessWidgetService(
        instance_id="instance-1",
        manifest=manifest,
        config={"threshold": 3},
        widget_root=workspace_tmp,
    )


async def _start_or_skip(service: ProcessWidgetService) -> None:
    try:
        await service.start()
    except ProcessServiceError as exc:
        if exc.code == "spawn_failed" and "Access is denied" in exc.message:
            pytest.skip("asyncio subprocess stdio pipes are blocked in this Windows sandbox")
        raise


@pytest.mark.asyncio
async def test_process_service_round_trips_start_state_health_refresh_config_and_stop(workspace_tmp: Path) -> None:
    service = _service(workspace_tmp, "normal")
    try:
        await _start_or_skip(service)
        assert await service.get_state() == {"started": True, "config": {"threshold": 3}}
        assert await service.health() == {"status": "running", "healthy": True, "started": True}
        assert await service.refresh(force=True) == {"refreshed": True, "force": True}
        await service.set_config({"threshold": 9})
        assert await service.get_state() == {"started": True, "config": {"threshold": 9}}
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_process_service_call_timeout_raises_structured_error(workspace_tmp: Path) -> None:
    service = _service(workspace_tmp, "timeout_get_state", runtime_policy={"refresh_timeout_seconds": 1})
    try:
        await _start_or_skip(service)
        with pytest.raises(ProcessServiceError) as exc_info:
            await service.get_state()
        assert exc_info.value.to_dict()["code"] == "timeout"
        assert exc_info.value.details["method"] == "get_state"
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_process_service_child_crash_reports_unhealthy_and_state_raises(workspace_tmp: Path) -> None:
    service = _service(workspace_tmp, "crash_get_state")
    try:
        await _start_or_skip(service)
        with pytest.raises(ProcessServiceError) as exc_info:
            await service.get_state()
        assert exc_info.value.code == "eof"
        health = await service.health()
        assert health["status"] == "unhealthy"
        assert health["exit_code"] == 7
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_process_service_stop_kills_hanging_child_within_deadline(workspace_tmp: Path) -> None:
    service = _service(workspace_tmp, "hang_stop", runtime_policy={"start_timeout_seconds": 1})
    await _start_or_skip(service)
    started_at = asyncio.get_running_loop().time()

    await service.stop()

    elapsed = asyncio.get_running_loop().time() - started_at
    assert elapsed < 4.5
    assert service._process is None


def _write_process_widget(widgets_dir: Path, *, command: list[str]) -> None:
    widget_root = widgets_dir / "process_widget"
    widget_root.mkdir(parents=True)
    (widgets_dir / "__init__.py").write_text('"""Test widgets."""\n', encoding="utf-8")
    (widget_root / "config.schema.json").write_text(json.dumps({"type": "object", "properties": {}}), encoding="utf-8")
    (widget_root / "renderer.tsx").write_text(
        "export function ProcessWidgetRenderer() { return null; }\n",
        encoding="utf-8",
    )
    (widget_root / "manifest.json").write_text(
        json.dumps(
            {
                "id": "process_widget",
                "version": "1.0.0",
                "name": "Process Widget",
                "category": "test",
                "description": "Process service test widget",
                "min_size": "2x2",
                "preferred_size": "2x2",
                "allowed_sizes": ["2x2"],
                "refresh_policy": {"mode": "manual", "interval_seconds": 0},
                "lifecycle_policy": {"stateful": True, "expires": False, "default_ttl_seconds": None},
                "runtime_policy": {
                    "start_timeout_seconds": 2,
                    "refresh_timeout_seconds": 1,
                    "heartbeat_timeout_seconds": 10,
                    "max_retries": 0,
                    "retry_backoff_seconds": 1,
                    "stale_after_seconds": 30,
                },
                "permissions": [],
                "renderer": {
                    "kind": "module",
                    "target": "react",
                    "module": "@widgets/process_widget/renderer",
                    "export_name": "ProcessWidgetRenderer",
                },
                "service": {"kind": "process", "command": command},
                "config_schema": "config.schema.json",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_registry_rejects_process_command_that_escapes_widget_package(workspace_tmp: Path) -> None:
    widgets_dir = workspace_tmp / "widgets"
    _write_process_widget(widgets_dir, command=["../runner.exe"])

    with pytest.raises(ValueError, match="traversal"):
        load_registry(widgets_dir)


def test_registry_rejects_absolute_process_command_outside_widget_package(workspace_tmp: Path) -> None:
    widgets_dir = workspace_tmp / "widgets"
    outside = (workspace_tmp / "outside.exe").resolve()
    _write_process_widget(widgets_dir, command=[str(outside)])

    with pytest.raises(ValueError, match="inside the widget package"):
        load_registry(widgets_dir)


def test_registry_accepts_in_package_relative_process_command(workspace_tmp: Path) -> None:
    widgets_dir = workspace_tmp / "widgets"
    widget_root = widgets_dir / "process_widget"
    _write_process_widget(widgets_dir, command=["bin/runner.exe", "--flag"])
    runner = widget_root / "bin" / "runner.exe"
    runner.parent.mkdir(parents=True)
    runner.write_text("placeholder\n", encoding="utf-8")

    registry = load_registry(widgets_dir)

    manifest = registry.get("process_widget").manifest
    assert manifest.service.kind == "process"
    assert manifest.service.command == ["bin/runner.exe", "--flag"]