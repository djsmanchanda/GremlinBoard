from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from gremlinboard_api.registry.loader import WidgetRegistry, load_registry
from gremlinboard_api.runtime.base import BaseWidgetService
from gremlinboard_api.runtime.events import EventBus
from gremlinboard_api.runtime.manager import RuntimeManager
from gremlinboard_api.runtime.process_service import ProcessServiceError, ProcessWidgetService


BACKEND_SOURCE = '''
from __future__ import annotations

from gremlinboard_api.runtime.base import BaseWidgetService


class GeneratedService(BaseWidgetService):
    async def start(self) -> None:
        self.mark_started()
        self.state = {
            "config": dict(self.config),
            "provider_registry_is_none": self.service_context.provider_registry is None,
        }

    async def stop(self) -> None:
        self.state["stopped"] = True

    async def health(self) -> dict:
        return {"status": "running", "healthy": True}

    async def get_state(self) -> dict:
        if self.config.get("crash"):
            raise SystemExit(7)
        return dict(self.state)

    async def refresh(self, *, force: bool = False) -> dict:
        self.state["refreshed"] = True
        self.state["force"] = force
        return dict(self.state)

    async def set_config(self, config: dict) -> None:
        await super().set_config(config)
        self.state["config"] = dict(config)
'''


@pytest.fixture
def workspace_tmp() -> Iterator[Path]:
    root = Path("data") / f"python-process-host-test-{uuid4().hex}"
    root.mkdir(parents=True)
    try:
        yield root.resolve()
    finally:
        shutil.rmtree(root, ignore_errors=True)

def _manifest(widget_id: str) -> dict[str, Any]:
    return {
        "id": widget_id,
        "version": "1.0.0",
        "name": widget_id.replace("_", " ").title(),
        "category": "test",
        "description": "Generated process host test widget",
        "min_size": "2x2",
        "preferred_size": "2x2",
        "allowed_sizes": ["2x2"],
        "refresh_policy": {"mode": "manual", "interval_seconds": 0},
        "lifecycle_policy": {"stateful": True, "expires": False, "default_ttl_seconds": None},
        "runtime_policy": {
            "start_timeout_seconds": 3,
            "refresh_timeout_seconds": 2,
            "heartbeat_timeout_seconds": 10,
            "max_retries": 0,
            "retry_backoff_seconds": 1,
            "stale_after_seconds": 30,
        },
        "permissions": [],
        "renderer": {
            "kind": "module",
            "target": "react",
            "module": f"@widgets/{widget_id}/renderer",
            "export_name": "GeneratedRenderer",
        },
        "service": {
            "kind": "python",
            "module": f"widgets.{widget_id}.backend",
            "class_name": "GeneratedService",
        },
        "config_schema": "config.schema.json",
    }


def _write_widget(widgets_dir: Path, widget_id: str) -> None:
    widgets_dir.mkdir(parents=True, exist_ok=True)
    (widgets_dir / "__init__.py").write_text('"""Test widgets."""\n', encoding="utf-8")
    widget_root = widgets_dir / widget_id
    widget_root.mkdir()
    (widget_root / "__init__.py").write_text('"""Test widget."""\n', encoding="utf-8")
    (widget_root / "backend.py").write_text(BACKEND_SOURCE, encoding="utf-8")
    (widget_root / "renderer.tsx").write_text(
        "export function GeneratedRenderer() { return null; }\n",
        encoding="utf-8",
    )
    (widget_root / "config.schema.json").write_text(
        json.dumps({"type": "object", "properties": {}}),
        encoding="utf-8",
    )
    (widget_root / "manifest.json").write_text(json.dumps(_manifest(widget_id)), encoding="utf-8")


def _host_command(widgets_parent: Path, widget_id: str) -> list[str]:
    api_root = Path(__file__).resolve().parents[1]
    bootstrap = (
        "import runpy,sys;"
        "sys.path.insert(0,sys.argv.pop(1));"
        "runpy.run_module('gremlinboard_api.runtime.python_process_host',run_name='__main__')"
    )
    return [
        str(Path(sys.executable).resolve()),
        "-I",
        "-c",
        bootstrap,
        str(api_root.resolve()),
        str(widgets_parent.resolve()),
        widget_id,
        "GeneratedService",
    ]


def _process_service(registry: WidgetRegistry, widget_id: str, config: dict[str, Any]) -> ProcessWidgetService:
    entry = registry.get(widget_id)
    return ProcessWidgetService(
        instance_id="instance-1",
        manifest=entry.manifest,
        config=config,
        widget_root=entry.root_dir,
        command=_host_command(registry.widgets_dir.parent, widget_id),
    )


@pytest.mark.asyncio
async def test_python_process_host_round_trips_real_generated_backend(workspace_tmp: Path) -> None:
    widgets_dir = (workspace_tmp / "host-round-trip" / "widgets").resolve()
    _write_widget(widgets_dir, "generated_round_trip")
    registry = load_registry(widgets_dir)
    service = _process_service(registry, "generated_round_trip", {"threshold": 3})

    try:
        await service.start()
        assert await service.get_state() == {
            "config": {"threshold": 3},
            "provider_registry_is_none": True,
        }
        assert await service.health() == {"status": "running", "healthy": True}
        await service.set_config({"threshold": 9})
        refreshed = await service.refresh(force=True)
        assert refreshed["config"] == {"threshold": 9}
        assert refreshed["refreshed"] is True
        assert refreshed["force"] is True
        process = service._process
        assert process is not None
    finally:
        await service.stop()

    assert service._process is None
    assert process.returncode is not None


@pytest.mark.asyncio
async def test_python_process_host_crash_surfaces_through_health_and_exit(workspace_tmp: Path) -> None:
    widgets_dir = (workspace_tmp / "host-crash" / "widgets").resolve()
    _write_widget(widgets_dir, "generated_crash")
    registry = load_registry(widgets_dir)
    service = _process_service(registry, "generated_crash", {"crash": True})

    try:
        await service.start()
        with pytest.raises(ProcessServiceError) as exc_info:
            await service.get_state()
        assert exc_info.value.code == "eof"
        health = await service.health()
        assert health["healthy"] is False
        assert health["exit_code"] == 7
    finally:
        await service.stop()

    assert service._process is None


def _manager(registry: WidgetRegistry) -> RuntimeManager:
    return RuntimeManager(
        session_factory=None,  # type: ignore[arg-type]
        registry=registry,
        event_bus=EventBus(),
        board_id="board",
    )


def test_runtime_manager_isolates_non_core_python_widgets_only_by_default(
    workspace_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widgets_dir = (workspace_tmp / "manager-default" / "widgets").resolve()
    _write_widget(widgets_dir, "generated_widget")
    _write_widget(widgets_dir, "core_widget")
    registry = load_registry(widgets_dir)
    registry.set_plugin_metadata("generated_widget", is_core=False, source_type="generated")
    monkeypatch.delenv("GREMLINBOARD_ISOLATE_GENERATED", raising=False)
    manager = _manager(registry)

    generated = manager._build_service(
        manifest=registry.get("generated_widget").manifest,
        instance_id="generated-instance",
        config={},
    )
    core = manager._build_service(
        manifest=registry.get("core_widget").manifest,
        instance_id="core-instance",
        config={},
    )

    assert isinstance(generated, ProcessWidgetService)
    assert isinstance(core, BaseWidgetService)
    assert not isinstance(core, ProcessWidgetService)


def test_runtime_manager_isolation_escape_hatch_is_read_at_construction(
    workspace_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widgets_dir = (workspace_tmp / "manager-disabled" / "widgets").resolve()
    _write_widget(widgets_dir, "generated_disabled")
    registry = load_registry(widgets_dir)
    registry.set_plugin_metadata("generated_disabled", is_core=False, source_type="generated")
    monkeypatch.setenv("GREMLINBOARD_ISOLATE_GENERATED", "0")
    manager = _manager(registry)
    monkeypatch.setenv("GREMLINBOARD_ISOLATE_GENERATED", "1")

    # The in-process path imports widgets.<id>.backend; a 'widgets' package
    # cached from another test's temp dir would shadow this one. Pop entries
    # permanently (monkeypatch.delitem would restore the stale package at
    # teardown and poison later in-process imports in the suite).
    def _purge_widgets_modules() -> None:
        for cached in [name for name in sys.modules if name == "widgets" or name.startswith("widgets.")]:
            sys.modules.pop(cached, None)

    _purge_widgets_modules()
    try:
        service = manager._build_service(
            manifest=registry.get("generated_disabled").manifest,
            instance_id="generated-instance",
            config={},
        )
    finally:
        _purge_widgets_modules()

    assert isinstance(service, BaseWidgetService)
    assert not isinstance(service, ProcessWidgetService)
