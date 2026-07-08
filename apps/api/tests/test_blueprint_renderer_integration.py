
from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from gremlinboard_api.registry.loader import load_registry
from gremlinboard_api.schemas.blueprint import validate_blueprint
from gremlinboard_api.schemas.contracts import (
    ModuleRendererTarget,
    WidgetManifest,
    WidgetPluginInstallRequest,
    WidgetPluginUpdateRequest,
    WidgetSpecDraft,
)
from gremlinboard_api.services.scaffold_generator import WidgetScaffoldGenerator

from .runtime_test_harness import RuntimeTestHarness


def _blueprint(widget_id: str) -> dict[str, object]:
    return {
        "blueprint_version": "1",
        "widget_id": widget_id,
        "layouts": {
            "medium": {
                "type": "stack",
                "gap": "md",
                "children": [
                    {"type": "text", "literal": "Blueprint widget", "variant": "title"},
                    {
                        "type": "key_value",
                        "entries": [{"label": "Summary", "value_path": "output.summary"}],
                    },
                ],
            }
        },
    }


def _backend_source(class_name: str, version: str) -> str:
    return f"""
from __future__ import annotations

from gremlinboard_api.runtime.base import BaseWidgetService


class {class_name}(BaseWidgetService):
    async def start(self) -> None:
        self.state = await self.get_state()

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        return {{"status": "running"}}

    async def get_state(self) -> dict[str, object]:
        return {{"output": {{"summary": "v{version}"}}, "manifest_version": self.manifest.version}}
""".strip() + "\n"


def _blueprint_package(*, widget_id: str, version: str = "1.0.0") -> dict[str, object]:
    class_name = "BlueprintWidgetService"
    return {
        "manifest": {
            "id": widget_id,
            "version": version,
            "name": widget_id.replace("_", " ").title(),
            "category": "test",
            "description": "Blueprint renderer test widget.",
            "min_size": "2x2",
            "preferred_size": "2x2",
            "allowed_sizes": ["2x2"],
            "refresh_policy": {"mode": "manual", "interval_seconds": 0},
            "lifecycle_policy": {"stateful": True, "expires": False, "default_ttl_seconds": None},
            "runtime_policy": {
                "start_timeout_seconds": 5,
                "refresh_timeout_seconds": 5,
                "heartbeat_timeout_seconds": 10,
                "max_retries": 1,
                "retry_backoff_seconds": 1,
                "stale_after_seconds": 30,
            },
            "permissions": [],
            "renderer": {"kind": "blueprint", "blueprint": "view.blueprint.json"},
            "service": {"module": f"widgets.{widget_id}.backend", "class_name": class_name},
            "config_schema": "config.schema.json",
        },
        "config_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "backend_source": _backend_source(class_name, version),
        "blueprint": _blueprint(widget_id),
    }


def _write_package(root: Path, package: dict[str, object], *, include_blueprint: bool = True) -> None:
    manifest = package["manifest"]
    assert isinstance(manifest, dict)
    widget_id = str(manifest["id"])
    widget_root = root / widget_id
    widget_root.mkdir(parents=True)
    (widget_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (widget_root / "config.schema.json").write_text(
        json.dumps(package["config_schema"], indent=2) + "\n",
        encoding="utf-8",
    )
    (widget_root / "backend.py").write_text(str(package["backend_source"]), encoding="utf-8")
    if include_blueprint:
        (widget_root / "view.blueprint.json").write_text(
            json.dumps(package["blueprint"], indent=2) + "\n",
            encoding="utf-8",
        )
    (widget_root / "__init__.py").write_text('"""Test widget package."""\n', encoding="utf-8")


def test_manifest_renderer_defaults_to_module_and_accepts_blueprint_shape() -> None:
    legacy = _blueprint_package(widget_id="legacy_widget")
    legacy_manifest = dict(legacy["manifest"])
    legacy_manifest["renderer"] = {
        "target": "react",
        "module": "@widgets/legacy_widget/renderer",
        "export_name": "LegacyWidgetRenderer",
    }

    manifest = WidgetManifest.model_validate(legacy_manifest)
    assert isinstance(manifest.renderer, ModuleRendererTarget)
    assert manifest.renderer.kind == "module"

    blueprint_manifest = WidgetManifest.model_validate(_blueprint_package(widget_id="blueprint_widget")["manifest"])
    assert blueprint_manifest.renderer.kind == "blueprint"
    assert blueprint_manifest.renderer.blueprint == "view.blueprint.json"


def test_registry_loads_blueprint_package_without_renderer_file() -> None:
    root = Path("data") / f"blueprint-registry-{uuid4().hex}"
    try:
        root.mkdir(parents=True)
        _write_package(root, _blueprint_package(widget_id="blueprint_widget"))

        registry = load_registry(root)

        entry = registry.get("blueprint_widget")
        assert entry.blueprint is not None
        assert entry.blueprint["widget_id"] == "blueprint_widget"
        assert not (entry.root_dir / "renderer.tsx").exists()
    finally:
        if root.exists():
            shutil.rmtree(root)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda package: package, "missing view.blueprint.json"),
        (lambda package: package["blueprint"].pop("layouts"), "invalid widget blueprint"),
        (lambda package: package["blueprint"].update({"widget_id": "other_widget"}), "widget_id must match"),
    ],
)
def test_registry_rejects_invalid_blueprint_packages(mutate, match: str) -> None:
    root = Path("data") / f"blueprint-registry-invalid-{uuid4().hex}"
    try:
        root.mkdir(parents=True)
        package = _blueprint_package(widget_id="blueprint_widget")
        mutate(package)
        include_blueprint = "missing" not in match
        _write_package(root, package, include_blueprint=include_blueprint)

        with pytest.raises((FileNotFoundError, ValueError), match=match):
            load_registry(root)
    finally:
        if root.exists():
            shutil.rmtree(root)


@pytest.mark.asyncio
async def test_plugin_install_update_and_rollback_preserve_blueprint_file() -> None:
    harness = await RuntimeTestHarness.create()
    try:
        widget_id = "blueprint_roundtrip"
        version_one = _blueprint_package(widget_id=widget_id, version="1.0.0")
        version_two = _blueprint_package(widget_id=widget_id, version="2.0.0")
        version_two["blueprint"] = _blueprint(widget_id) | {
            "defaults": {"status": {"type": "text", "literal": "v2", "variant": "caption"}}
        }

        await harness.plugin_manager.install_widget(WidgetPluginInstallRequest(package=version_one))
        await harness.plugin_manager.update_widget(widget_id, WidgetPluginUpdateRequest(package=version_two))
        await harness.plugin_manager.rollback_widget(widget_id, "1.0.0")

        widget_root = harness.widgets_dir / widget_id
        restored = json.loads((widget_root / "view.blueprint.json").read_text(encoding="utf-8"))
        assert restored == version_one["blueprint"]
        assert not (widget_root / "renderer.tsx").exists()
        assert harness.registry.get(widget_id).blueprint == version_one["blueprint"]
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_board_payload_includes_blueprint_for_blueprint_widget() -> None:
    harness = await RuntimeTestHarness.create()
    try:
        package = _blueprint_package(widget_id="board_blueprint")
        await harness.plugin_manager.install_widget(WidgetPluginInstallRequest(package=package))

        create_response = await harness.client.post(
            "/api/board/widgets",
            json={"widget_id": "board_blueprint", "title": "Board Blueprint", "size": "2x2", "config": {}},
        )
        assert create_response.status_code == 200
        assert create_response.json()["blueprint"] == package["blueprint"]

        board_response = await harness.client.get("/api/board")
        assert board_response.status_code == 200
        assert board_response.json()["widgets"][0]["blueprint"] == package["blueprint"]
    finally:
        await harness.close()


def test_scaffold_generator_emits_valid_blueprint_package_without_renderer() -> None:
    spec = WidgetSpecDraft.model_validate(
        {
            "id": "ops_status",
            "name": "Ops Status",
            "category": "custom",
            "description": "Operational status snapshot",
            "min_size": "2x2",
            "preferred_size": "4x2",
            "refresh_policy": {"mode": "interval", "interval_seconds": 300},
            "source_type": "generated",
            "permissions": ["network"],
            "output_schema": {"summary": "string", "status": "string"},
            "renderer_type": "card",
            "lifecycle_policy": {"expires": False, "stateful": True},
        }
    )

    artifact = WidgetScaffoldGenerator().generate(spec=spec, version="0.1.0", artifact_version=1)
    package = artifact["package"]

    assert "renderer_source" not in package
    assert package["manifest"]["renderer"] == {"kind": "blueprint", "blueprint": "view.blueprint.json"}
    assert any(file["path"] == "widgets/ops_status/view.blueprint.json" for file in artifact["files"])
    assert not any(file["path"].endswith("renderer.tsx") for file in artifact["files"])
    assert validate_blueprint(package["blueprint"]).widget_id == "ops_status"
