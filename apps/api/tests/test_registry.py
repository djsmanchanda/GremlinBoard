import json
from pathlib import Path

import pytest

from gremlinboard_api.config import settings
from gremlinboard_api.registry.loader import load_registry


def test_registry_loads_expected_widgets() -> None:
    registry = load_registry(settings.widgets_dir)
    widget_ids = sorted(entry.manifest.id for entry in registry.all())

    assert widget_ids == ["agent_overview", "countdown", "news", "pinboard", "sports", "trending"]
    assert registry.get("sports").manifest.preferred_size.value == "4x2"
    assert "4x4" in [size.value for size in registry.get("pinboard").manifest.allowed_sizes]


def _write_widget_package(root: Path, widget_id: str) -> None:
    widget_root = root / widget_id
    widget_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": widget_id,
        "version": "1.0.0",
        "name": widget_id.title(),
        "category": "test",
        "description": "test widget",
        "min_size": "2x2",
        "preferred_size": "2x2",
        "allowed_sizes": ["2x2"],
        "refresh_policy": {"mode": "manual", "interval_seconds": 0},
        "lifecycle_policy": {"stateful": False, "expires": False, "default_ttl_seconds": None},
        "permissions": [],
        "renderer": {
            "kind": "module",
            "target": "react",
            "module": f"@widgets/{widget_id}/renderer",
            "export_name": "Renderer",
        },
        "service": {
            "kind": "python",
            "module": f"widgets.{widget_id}.backend",
            "class_name": "Service",
        },
        "config_schema": "config.schema.json",
    }
    (widget_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (widget_root / "config.schema.json").write_text(json.dumps({"type": "object", "properties": {}}), encoding="utf-8")
    (widget_root / "backend.py").write_text(
        "from gremlinboard_api.runtime.base import BaseWidgetService\n\n\nclass Service(BaseWidgetService):\n    pass\n",
        encoding="utf-8",
    )
    (widget_root / "renderer.tsx").write_text(
        "export function Renderer() { return null; }\n",
        encoding="utf-8",
    )


def test_registry_loads_widgets_from_both_core_and_user_roots(tmp_path: Path) -> None:
    core_dir = tmp_path / "core" / "widgets"
    user_dir = tmp_path / "user" / "widgets"
    _write_widget_package(core_dir, "core_widget")
    _write_widget_package(user_dir, "generated_widget")

    registry = load_registry(core_dir, user_dir)

    assert sorted(entry.manifest.id for entry in registry.all()) == ["core_widget", "generated_widget"]
    assert registry.get("core_widget").is_core is True
    assert registry.get("core_widget").source_type == "core"
    assert registry.get("generated_widget").is_core is False
    assert registry.get("generated_widget").source_type == "generated"


def test_registry_rejects_user_widget_that_shadows_core_widget_id(tmp_path: Path) -> None:
    core_dir = tmp_path / "core" / "widgets"
    user_dir = tmp_path / "user" / "widgets"
    _write_widget_package(core_dir, "shared_id")
    _write_widget_package(user_dir, "shared_id")

    with pytest.raises(ValueError, match="shadow"):
        load_registry(core_dir, user_dir)
