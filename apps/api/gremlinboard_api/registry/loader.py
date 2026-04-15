from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gremlinboard_api.schemas.contracts import WidgetManifest, WidgetRegistryEntry
from gremlinboard_api.specs.widget_ids import sanitize_widget_id, widget_service_module


@dataclass(slots=True)
class LoadedWidget:
    manifest: WidgetManifest
    root_dir: Path
    config_schema: dict[str, Any]


class WidgetRegistry:
    def __init__(self, widgets_dir: Path):
        self.widgets_dir = widgets_dir
        self._entries: dict[str, LoadedWidget] = {}

    def load(self) -> None:
        entries: dict[str, LoadedWidget] = {}
        for manifest_path in sorted(self.widgets_dir.glob("*/manifest.json")):
            widget_root, raw_manifest = self._normalize_widget_package(manifest_path.parent)
            manifest = WidgetManifest.model_validate(raw_manifest)
            schema_path = widget_root / raw_manifest["config_schema"]
            renderer_path = widget_root / "renderer.tsx"
            backend_path = widget_root / "backend.py"

            if not schema_path.exists():
                raise FileNotFoundError(f"missing config schema for widget {manifest.id}")
            if not renderer_path.exists():
                raise FileNotFoundError(f"missing renderer.tsx for widget {manifest.id}")
            if not backend_path.exists():
                raise FileNotFoundError(f"missing backend.py for widget {manifest.id}")
            renderer_source = renderer_path.read_text(encoding="utf-8")
            if not _renderer_exports_symbol(renderer_source, manifest.renderer.export_name):
                raise ValueError(f"renderer.tsx for widget {manifest.id} must export '{manifest.renderer.export_name}'")

            config_schema = json.loads(schema_path.read_text(encoding="utf-8"))
            entries[manifest.id] = LoadedWidget(
                manifest=manifest,
                root_dir=widget_root,
                config_schema=config_schema,
            )

        self._entries = entries

    def _normalize_widget_package(self, widget_root: Path) -> tuple[Path, dict[str, Any]]:
        manifest_path = widget_root / "manifest.json"
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        canonical_id = sanitize_widget_id(str(raw_manifest.get("id") or widget_root.name))
        changed = False

        if raw_manifest.get("id") != canonical_id:
            raw_manifest["id"] = canonical_id
            changed = True

        service = raw_manifest.setdefault("service", {})
        expected_module = widget_service_module(canonical_id)
        if service.get("module") != expected_module:
            service["module"] = expected_module
            changed = True

        target_root = self.widgets_dir / canonical_id
        if widget_root != target_root:
            if target_root.exists():
                raise FileExistsError(f"cannot migrate widget '{widget_root.name}' to '{canonical_id}'; target already exists")
            widget_root.rename(target_root)
            widget_root = target_root
            changed = True

        if changed:
            (widget_root / "manifest.json").write_text(json.dumps(raw_manifest, indent=2) + "\n", encoding="utf-8")

        init_path = widget_root / "__init__.py"
        if not init_path.exists():
            init_path.write_text('"""Widget package."""\n', encoding="utf-8")

        return widget_root, raw_manifest

    def all(self) -> list[LoadedWidget]:
        return list(self._entries.values())

    def get(self, widget_id: str) -> LoadedWidget:
        entry = self._entries.get(widget_id)
        if entry is None:
            raise KeyError(f"widget '{widget_id}' is not registered")
        return entry

    def as_response(self) -> dict[str, WidgetRegistryEntry]:
        return {
            widget_id: WidgetRegistryEntry(manifest=entry.manifest, config_schema=entry.config_schema)
            for widget_id, entry in self._entries.items()
        }

    @property
    def size(self) -> int:
        return len(self._entries)


def load_registry(widgets_dir: Path) -> WidgetRegistry:
    registry = WidgetRegistry(widgets_dir)
    registry.load()
    return registry


def _renderer_exports_symbol(renderer_source: str, export_name: str) -> bool:
    patterns = (
        rf"export\s+function\s+{re.escape(export_name)}\s*\(",
        rf"export\s+async\s+function\s+{re.escape(export_name)}\s*\(",
        rf"export\s+(?:const|let|var)\s+{re.escape(export_name)}\s*=",
        rf"export\s+class\s+{re.escape(export_name)}\b",
    )
    return any(re.search(pattern, renderer_source) for pattern in patterns)
