import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from gremlinboard_api.registry.loader import load_registry
from gremlinboard_api.schemas.contracts import WidgetSpecDraft
from gremlinboard_api.specs.pipeline import build_manifest_preview_with_version, scaffold_preview


def test_spec_and_manifest_normalize_widget_id_to_python_safe_slug() -> None:
    spec = WidgetSpecDraft.model_validate(
        {
            "id": "Ops Status! 2026",
            "name": "Ops Status 2026",
            "category": "custom",
            "description": "Operational status snapshot",
            "min_size": "2x2",
            "preferred_size": "4x2",
            "refresh_policy": {"mode": "interval", "interval_seconds": 300},
            "source_type": "generated",
            "permissions": ["network"],
            "output_schema": {"summary": "string"},
            "renderer_type": "card",
            "lifecycle_policy": {"expires": False, "stateful": True},
        }
    )

    manifest = build_manifest_preview_with_version(spec, version="0.1.0")
    preview = scaffold_preview(spec)

    assert spec.id == "ops_status_2026"
    assert manifest["id"] == "ops_status_2026"
    assert manifest["service"]["module"] == "widgets.ops_status_2026.backend"
    assert preview["widget_root"] == "widgets/ops_status_2026"
    assert "apps/api/tests/test_ops_status_2026_widget.py" in preview["files"]


def test_registry_load_rejects_invalid_widget_directory_and_manifest() -> None:
    root = Path("data") / f"registry-invalid-test-{uuid4().hex}"
    legacy_root = root / "Ops Status!"
    try:
        legacy_root.mkdir(parents=True)
        (root / "__init__.py").write_text('"""Widgets root."""\n', encoding="utf-8")
        (legacy_root / "__init__.py").write_text('"""Widget package."""\n', encoding="utf-8")
        (legacy_root / "config.schema.json").write_text(json.dumps({"type": "object", "properties": {}}), encoding="utf-8")
        (legacy_root / "backend.py").write_text("from gremlinboard_api.runtime.base import BaseWidgetService\n", encoding="utf-8")
        (legacy_root / "renderer.tsx").write_text("export function LegacyRenderer() { return null; }\n", encoding="utf-8")
        (legacy_root / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "Ops Status!",
                    "version": "0.1.0",
                    "name": "Ops Status!",
                    "category": "custom",
                    "description": "Legacy widget",
                    "min_size": "2x2",
                    "preferred_size": "4x2",
                    "allowed_sizes": ["2x2", "4x2"],
                    "refresh_policy": {"mode": "interval", "interval_seconds": 300},
                    "lifecycle_policy": {"stateful": True, "expires": False, "default_ttl_seconds": None},
                    "runtime_policy": {
                        "start_timeout_seconds": 10,
                        "refresh_timeout_seconds": 10,
                        "heartbeat_timeout_seconds": 120,
                        "max_retries": 3,
                        "retry_backoff_seconds": 2,
                        "stale_after_seconds": 300,
                    },
                    "permissions": ["network"],
                    "renderer": {"target": "card"},
                    "service": {"module": "widgets.Ops Status!.backend", "class_name": "OpsStatusService"},
                    "config_schema": "config.schema.json",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="canonical id"):
            load_registry(root)
    finally:
        if root.exists():
            shutil.rmtree(root)
