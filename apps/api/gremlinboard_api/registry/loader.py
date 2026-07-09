from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gremlinboard_api.schemas.blueprint import collect_binding_paths, validate_blueprint
from gremlinboard_api.schemas.contracts import (
    BlueprintRendererTarget,
    ModuleRendererTarget,
    PythonServiceTarget,
    WidgetManifest,
    WidgetRegistryEntry,
)
from gremlinboard_api.specs.widget_ids import sanitize_widget_id, widget_service_module

DANGEROUS_BACKEND_IMPORTS = {"os", "pathlib", "socket", "subprocess", "sys"}
DANGEROUS_RENDERER_IMPORTS = {
    "child_process",
    "dgram",
    "fs",
    "net",
    "node:child_process",
    "node:dgram",
    "node:fs",
    "node:net",
    "node:os",
    "node:path",
    "node:tls",
    "node:worker_threads",
    "os",
    "path",
    "tls",
    "worker_threads",
}


@dataclass(slots=True)
class LoadedWidget:
    manifest: WidgetManifest
    root_dir: Path
    config_schema: dict[str, Any]
    blueprint: dict[str, Any] | None = None


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
            backend_path = widget_root / "backend.py"

            if not schema_path.exists():
                raise FileNotFoundError(f"missing config schema for widget {manifest.id}")
            if isinstance(manifest.service, PythonServiceTarget):
                if not backend_path.exists():
                    raise FileNotFoundError(f"missing backend.py for widget {manifest.id}")
                backend_source = backend_path.read_text(encoding="utf-8")
                _reject_dangerous_backend_imports(backend_source, manifest.id)
            blueprint: dict[str, Any] | None = None
            if isinstance(manifest.renderer, BlueprintRendererTarget):
                blueprint = _load_widget_blueprint(widget_root, manifest_id=manifest.id)
            elif isinstance(manifest.renderer, ModuleRendererTarget):
                renderer_path = widget_root / "renderer.tsx"
                if not renderer_path.exists():
                    raise FileNotFoundError(f"missing renderer.tsx for widget {manifest.id}")
                renderer_source = renderer_path.read_text(encoding="utf-8")
                _reject_dangerous_renderer_imports(renderer_source, manifest.id)
                if not _renderer_exports_symbol(renderer_source, manifest.renderer.export_name):
                    raise ValueError(f"renderer.tsx for widget {manifest.id} must export '{manifest.renderer.export_name}'")

            config_schema = json.loads(schema_path.read_text(encoding="utf-8"))
            entries[manifest.id] = LoadedWidget(
                manifest=manifest,
                root_dir=widget_root,
                config_schema=config_schema,
                blueprint=blueprint,
            )

        self._entries = entries

    def _normalize_widget_package(self, widget_root: Path) -> tuple[Path, dict[str, Any]]:
        manifest_path = widget_root / "manifest.json"
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        validate_widget_manifest_paths(raw_manifest, widget_root=widget_root, widgets_dir=self.widgets_dir)

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
            widget_id: WidgetRegistryEntry(
                manifest=entry.manifest,
                config_schema=entry.config_schema,
                blueprint=entry.blueprint,
            )
            for widget_id, entry in self._entries.items()
        }

    def blueprints_by_widget_id(self) -> dict[str, dict[str, Any]]:
        return {widget_id: entry.blueprint for widget_id, entry in self._entries.items() if entry.blueprint is not None}

    @property
    def size(self) -> int:
        return len(self._entries)


def load_registry(widgets_dir: Path) -> WidgetRegistry:
    registry = WidgetRegistry(widgets_dir)
    registry.load()
    return registry


def validate_widget_manifest_paths(
    raw_manifest: dict[str, Any], *, widget_root: Path | None = None, widgets_dir: Path | None = None
) -> str:
    raw_id = str(raw_manifest.get("id") or "")
    canonical_id = sanitize_widget_id(raw_id or (widget_root.name if widget_root is not None else ""))
    if raw_id != canonical_id:
        raise ValueError(f"widget manifest id '{raw_id}' must match canonical id '{canonical_id}'")

    if widget_root is not None:
        if widget_root.name != canonical_id:
            raise ValueError(f"widget directory '{widget_root.name}' must match manifest id '{canonical_id}'")
        if widgets_dir is not None and widget_root.parent != widgets_dir:
            raise ValueError(f"widget '{canonical_id}' must be loaded from the configured widgets directory")

    service = raw_manifest.get("service")
    if not isinstance(service, dict):
        raise ValueError(f"widget {canonical_id} manifest must include a service target")
    service_kind = service.get("kind", "python")
    if service_kind == "python":
        expected_service_module = widget_service_module(canonical_id)
        service_module = service.get("module")
        if not isinstance(service_module, str) or not service_module.startswith("widgets."):
            raise ValueError(f"service.module for widget {canonical_id} must be under widgets.*")
        if service_module != expected_service_module:
            raise ValueError(f"service.module for widget {canonical_id} must be '{expected_service_module}'")
    elif service_kind == "process":
        if "module" in service or "class_name" in service:
            raise ValueError(f"process service for widget {canonical_id} must not declare a python module")
        _validate_process_service_command(service, widget_root=widget_root, widget_id=canonical_id)
    else:
        raise ValueError(f"service.kind for widget {canonical_id} must be 'python' or 'process'")
    renderer = raw_manifest.get("renderer")
    if not isinstance(renderer, dict):
        raise ValueError(f"widget {canonical_id} manifest must include a renderer target")
    renderer_kind = renderer.get("kind", "module")
    if renderer_kind == "module":
        expected_renderer_module = f"@widgets/{canonical_id}/renderer"
        if renderer.get("module") != expected_renderer_module:
            raise ValueError(f"renderer.module for widget {canonical_id} must be '{expected_renderer_module}'")
    elif renderer_kind == "blueprint":
        if renderer.get("blueprint") != "view.blueprint.json":
            raise ValueError(f"renderer.blueprint for widget {canonical_id} must be 'view.blueprint.json'")
    else:
        raise ValueError(f"renderer.kind for widget {canonical_id} must be 'module' or 'blueprint'")

    if raw_manifest.get("config_schema") != "config.schema.json":
        raise ValueError(f"config_schema for widget {canonical_id} must be 'config.schema.json'")

    return canonical_id


def _validate_process_service_command(
    service: dict[str, Any], *, widget_root: Path | None, widget_id: str
) -> None:
    command = service.get("command")
    if not isinstance(command, list) or not command:
        raise ValueError(f"service.command for widget {widget_id} must be a non-empty argv list")
    if any(not isinstance(part, str) or not part for part in command):
        raise ValueError(f"service.command for widget {widget_id} must contain non-empty strings")

    executable = command[0]
    normalized = executable.replace("\\", "/")
    if ".." in {part for part in normalized.split("/") if part}:
        raise ValueError(f"service.command for widget {widget_id} must not contain '..' traversal")
    if _is_bare_executable_name(executable):
        return
    executable_path = Path(executable)
    if widget_root is None:
        return
    if executable_path.drive and not executable_path.is_absolute():
        raise ValueError(f"service.command for widget {widget_id} must not use a drive-relative path")
    candidate = executable_path if executable_path.is_absolute() else widget_root / executable_path
    root = widget_root.resolve(strict=False)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"service.command for widget {widget_id} must stay inside the widget package directory") from exc


def _is_bare_executable_name(value: str) -> bool:
    path = Path(value)
    return "/" not in value and "\\" not in value and not path.is_absolute() and not path.drive


def _load_widget_blueprint(widget_root: Path, *, manifest_id: str) -> dict[str, Any]:
    blueprint_path = widget_root / "view.blueprint.json"
    if not blueprint_path.exists():
        raise FileNotFoundError(f"missing view.blueprint.json for widget {manifest_id}")
    try:
        raw_blueprint = json.loads(blueprint_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"view.blueprint.json for widget {manifest_id} must be valid JSON") from exc
    blueprint = validate_blueprint(raw_blueprint)
    if blueprint.widget_id != manifest_id:
        raise ValueError(f"view.blueprint.json widget_id must match manifest id '{manifest_id}'")
    collect_binding_paths(blueprint)
    return blueprint.model_dump(mode="json", exclude_none=True)


def validate_widget_package_source(*, backend_source: str, renderer_source: str, widget_id: str) -> None:
    _reject_dangerous_backend_imports(backend_source, widget_id)
    _reject_dangerous_renderer_imports(renderer_source, widget_id)


def _renderer_exports_symbol(renderer_source: str, export_name: str) -> bool:
    patterns = (
        rf"export\s+function\s+{re.escape(export_name)}\s*\(",
        rf"export\s+async\s+function\s+{re.escape(export_name)}\s*\(",
        rf"export\s+(?:const|let|var)\s+{re.escape(export_name)}\s*=",
        rf"export\s+class\s+{re.escape(export_name)}\b",
    )
    return any(re.search(pattern, renderer_source) for pattern in patterns)


def _reject_dangerous_backend_imports(backend_source: str, widget_id: str) -> None:
    try:
        tree = ast.parse(backend_source)
    except SyntaxError as exc:
        raise ValueError(f"backend.py for widget {widget_id} must be valid Python") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = [alias.name.split(".", 1)[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported = [node.module.split(".", 1)[0]]
        else:
            continue
        blocked = sorted(set(imported) & DANGEROUS_BACKEND_IMPORTS)
        if blocked:
            raise ValueError(f"backend.py for widget {widget_id} imports blocked module(s): {', '.join(blocked)}")


def _reject_dangerous_renderer_imports(renderer_source: str, widget_id: str) -> None:
    patterns = (
        r"\bimport\s+(?:[^'\"\n]+\s+from\s+)?['\"]([^'\"]+)['\"]",
        r"\bimport\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
    )
    imports = {
        match.group(1)
        for pattern in patterns
        for match in re.finditer(pattern, renderer_source)
    }
    blocked = sorted(module for module in imports if module.split("/", 1)[0] in DANGEROUS_RENDERER_IMPORTS or module in DANGEROUS_RENDERER_IMPORTS)
    if blocked:
        raise ValueError(f"renderer.tsx for widget {widget_id} imports blocked module(s): {', '.join(blocked)}")
