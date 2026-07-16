from __future__ import annotations

import json
import ast
import re
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gremlinboard_api.registry.loader import (
    WidgetRegistry,
    validate_widget_manifest_paths,
    validate_widget_package_source,
)
from gremlinboard_api.repositories.board import BoardRepository
from gremlinboard_api.schemas.blueprint import collect_binding_paths, validate_blueprint
from gremlinboard_api.repositories.plugins import (
    PluginRepository,
    decode_version_package,
    serialize_plugin,
    serialize_plugin_version,
)
from gremlinboard_api.schemas.contracts import (
    BlueprintRendererTarget,
    ModuleRendererTarget,
    WidgetManifest,
    WidgetPluginInstallRequest,
    WidgetPluginRead,
    WidgetPluginUpdateRequest,
    WidgetPluginVersionRead,
)


class PluginManagerService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        widgets_dir: Path,
        registry: WidgetRegistry,
    ) -> None:
        self.session_factory = session_factory
        self.widgets_dir = widgets_dir
        self.registry = registry

    async def sync_with_filesystem(self) -> None:
        async with self.session_factory() as session:
            repository = PluginRepository(session)
            for entry in self.registry.all():
                existing = await repository.get_plugin(entry.manifest.id)
                record = await repository.upsert_plugin(
                    widget_id=entry.manifest.id,
                    version=entry.manifest.version,
                    enabled=existing.enabled if existing else True,
                    installed=True,
                    is_core=existing.is_core if existing else entry.is_core,
                    source_type=existing.source_type if existing else entry.source_type,
                    source_ref=existing.source_ref if existing else str(entry.root_dir),
                    last_error=None,
                )
                self.registry.set_plugin_metadata(
                    entry.manifest.id,
                    is_core=record.is_core,
                    source_type=record.source_type,
                )
                versions = await repository.list_versions(entry.manifest.id)
                if not any(version.version == entry.manifest.version for version in versions):
                    await repository.create_version_snapshot(
                        widget_id=entry.manifest.id,
                        version=entry.manifest.version,
                        package=self._read_package(entry.root_dir),
                    )

    async def list_plugins(self) -> list[WidgetPluginRead]:
        async with self.session_factory() as session:
            repository = PluginRepository(session)
            return [serialize_plugin(record) for record in await repository.list_plugins()]

    async def get_plugin(self, widget_id: str) -> WidgetPluginRead | None:
        async with self.session_factory() as session:
            repository = PluginRepository(session)
            record = await repository.get_plugin(widget_id)
            return serialize_plugin(record) if record is not None else None

    async def list_versions(self, widget_id: str) -> list[WidgetPluginVersionRead]:
        async with self.session_factory() as session:
            repository = PluginRepository(session)
            return [serialize_plugin_version(record) for record in await repository.list_versions(widget_id)]

    async def install_widget(self, request: WidgetPluginInstallRequest) -> WidgetPluginRead:
        package = request.package.model_dump(exclude_none=True)
        manifest = self._validate_package(package)
        widget_root = self.widgets_dir / manifest.id
        if widget_root.exists():
            raise ValueError(f"widget '{manifest.id}' already exists")

        self._write_package(widget_root, package)
        self.registry.load()
        await self.sync_with_filesystem()

        async with self.session_factory() as session:
            repository = PluginRepository(session)
            record = await repository.upsert_plugin(
                widget_id=manifest.id,
                version=manifest.version,
                enabled=request.enabled,
                installed=True,
                is_core=False,
                source_type=request.source_type,
                source_ref=request.source_ref or str(widget_root),
                last_error=None,
            )
            self.registry.set_plugin_metadata(
                manifest.id,
                is_core=record.is_core,
                source_type=record.source_type,
            )
            await repository.create_version_snapshot(
                widget_id=manifest.id,
                version=manifest.version,
                package=package,
            )
            return serialize_plugin(record)

    async def update_widget(self, widget_id: str, request: WidgetPluginUpdateRequest) -> WidgetPluginRead:
        package = request.package.model_dump(exclude_none=True)
        manifest = self._validate_package(package)
        if manifest.id != widget_id:
            raise ValueError("package manifest id must match the widget being updated")

        async with self.session_factory() as session:
            repository = PluginRepository(session)
            plugin = await repository.get_plugin(widget_id)
            if plugin is None or not plugin.installed:
                raise ValueError(f"widget '{widget_id}' is not installed")
            if plugin.is_core:
                raise ValueError("core widgets cannot be updated through the plugin API")

            current_root = self.widgets_dir / widget_id
            if current_root.exists():
                current_entry = self.registry.get(widget_id)
                await repository.create_version_snapshot(
                    widget_id=widget_id,
                    version=plugin.version,
                    package=self._read_package(current_entry.root_dir),
                )

        self._write_package(self.widgets_dir / widget_id, package, replace=True)
        self.registry.load()
        await self.sync_with_filesystem()

        async with self.session_factory() as session:
            repository = PluginRepository(session)
            record = await repository.upsert_plugin(
                widget_id=widget_id,
                version=manifest.version,
                enabled=True,
                installed=True,
                is_core=False,
                source_type="manual",
                source_ref=request.source_ref or str(self.widgets_dir / widget_id),
                last_error=None,
            )
            self.registry.set_plugin_metadata(
                widget_id,
                is_core=record.is_core,
                source_type=record.source_type,
            )
            await repository.create_version_snapshot(
                widget_id=widget_id,
                version=manifest.version,
                package=package,
            )
            return serialize_plugin(record)

    async def rollback_widget(self, widget_id: str, version: str) -> WidgetPluginRead:
        async with self.session_factory() as session:
            repository = PluginRepository(session)
            plugin = await repository.get_plugin(widget_id)
            if plugin is None or not plugin.installed:
                raise ValueError(f"widget '{widget_id}' is not installed")
            if plugin.is_core:
                raise ValueError("core widgets cannot be rolled back through the plugin API")
            version_record = await repository.get_version(widget_id, version)
            if version_record is None:
                raise ValueError(f"widget '{widget_id}' does not have a stored version '{version}'")
            package = decode_version_package(version_record)
            self._validate_package(package)

        self._write_package(self.widgets_dir / widget_id, package, replace=True)
        self.registry.load()
        await self.sync_with_filesystem()

        async with self.session_factory() as session:
            repository = PluginRepository(session)
            record = await repository.upsert_plugin(
                widget_id=widget_id,
                version=version,
                enabled=True,
                installed=True,
                is_core=False,
                source_type="rollback",
                source_ref=str(self.widgets_dir / widget_id),
                last_error=None,
            )
            self.registry.set_plugin_metadata(
                widget_id,
                is_core=record.is_core,
                source_type=record.source_type,
            )
            await repository.create_version_snapshot(
                widget_id=widget_id,
                version=version,
                package=package,
                is_rollback=True,
            )
            return serialize_plugin(record)

    async def set_enabled(self, widget_id: str, enabled: bool) -> WidgetPluginRead:
        async with self.session_factory() as session:
            repository = PluginRepository(session)
            record = await repository.get_plugin(widget_id)
            if record is None or not record.installed:
                raise ValueError(f"widget '{widget_id}' is not installed")
            updated = await repository.upsert_plugin(
                widget_id=record.widget_id,
                version=record.version,
                enabled=enabled,
                installed=record.installed,
                is_core=record.is_core,
                source_type=record.source_type,
                source_ref=record.source_ref,
                last_error=record.last_error,
            )
            return serialize_plugin(updated)

    async def uninstall_widget(self, widget_id: str) -> WidgetPluginRead:
        async with self.session_factory() as session:
            plugin_repository = PluginRepository(session)
            board_repository = BoardRepository(session)
            plugin = await plugin_repository.get_plugin(widget_id)
            if plugin is None or not plugin.installed:
                raise ValueError(f"widget '{widget_id}' is not installed")
            if plugin.is_core:
                raise ValueError("core widgets cannot be uninstalled")
            if await board_repository.count_widget_instances_by_widget_id(widget_id) > 0:
                raise ValueError("widget cannot be uninstalled while active instances exist")

        widget_root = self.widgets_dir / widget_id
        if widget_root.exists():
            shutil.rmtree(widget_root)
        self.registry.load()

        async with self.session_factory() as session:
            repository = PluginRepository(session)
            plugin = await repository.get_plugin(widget_id)
            if plugin is None:
                raise ValueError(f"widget '{widget_id}' is not installed")
            updated = await repository.upsert_plugin(
                widget_id=plugin.widget_id,
                version=plugin.version,
                enabled=False,
                installed=False,
                is_core=plugin.is_core,
                source_type=plugin.source_type,
                source_ref=plugin.source_ref,
                last_error=None,
            )
            return serialize_plugin(updated)

    async def reload_registry(self) -> None:
        self.registry.load()
        await self.sync_with_filesystem()

    async def is_enabled(self, widget_id: str) -> bool:
        plugin = await self.get_plugin(widget_id)
        return bool(plugin and plugin.installed and plugin.enabled)

    def read_installed_package(self, widget_id: str) -> dict[str, Any] | None:
        try:
            entry = self.registry.get(widget_id)
        except KeyError:
            return None
        return self._read_package(entry.root_dir)

    @staticmethod
    def _read_package(widget_root: Path) -> dict[str, Any]:
        manifest = json.loads((widget_root / "manifest.json").read_text(encoding="utf-8"))
        package = {
            "manifest": manifest,
            "config_schema": json.loads((widget_root / "config.schema.json").read_text(encoding="utf-8")),
            "backend_source": (widget_root / "backend.py").read_text(encoding="utf-8"),
        }
        if manifest.get("renderer", {}).get("kind", "module") == "blueprint":
            package["blueprint"] = json.loads((widget_root / "view.blueprint.json").read_text(encoding="utf-8"))
        else:
            package["renderer_source"] = (widget_root / "renderer.tsx").read_text(encoding="utf-8")
        return package

    @staticmethod
    def _write_package(widget_root: Path, package: dict[str, Any], *, replace: bool = False) -> None:
        manifest_model = WidgetManifest.model_validate(package["manifest"])
        manifest = manifest_model.model_dump(mode="json")
        if replace and widget_root.exists():
            shutil.rmtree(widget_root)
        widget_root.mkdir(parents=True, exist_ok=True)
        (widget_root / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        (widget_root / "config.schema.json").write_text(
            json.dumps(package["config_schema"], indent=2) + "\n",
            encoding="utf-8",
        )
        (widget_root / "backend.py").write_text(package["backend_source"], encoding="utf-8")
        if isinstance(manifest_model.renderer, BlueprintRendererTarget):
            (widget_root / "view.blueprint.json").write_text(
                json.dumps(package["blueprint"], indent=2) + "\n",
                encoding="utf-8",
            )
        elif isinstance(manifest_model.renderer, ModuleRendererTarget):
            (widget_root / "renderer.tsx").write_text(str(package["renderer_source"]), encoding="utf-8")
        (widget_root / "__init__.py").write_text('"""Widget package."""\n', encoding="utf-8")

    @staticmethod
    def _validate_package(package: dict[str, Any]) -> WidgetManifest:
        validate_widget_manifest_paths(package["manifest"])
        manifest = WidgetManifest.model_validate(package["manifest"])
        backend_source = str(package["backend_source"])
        if isinstance(manifest.renderer, BlueprintRendererTarget):
            PluginManagerService._validate_blueprint_contract(package.get("blueprint"), widget_id=manifest.id)
            validate_widget_package_source(
                backend_source=backend_source,
                renderer_source="",
                widget_id=manifest.id,
                generated=True,
            )
        elif isinstance(manifest.renderer, ModuleRendererTarget):
            renderer_source = package.get("renderer_source")
            if not isinstance(renderer_source, str):
                raise ValueError("renderer_source is required for module renderer packages")
            validate_widget_package_source(
                backend_source=backend_source,
                renderer_source=renderer_source,
                widget_id=manifest.id,
                generated=True,
            )
            PluginManagerService._validate_renderer_contract(
                renderer_source=renderer_source,
                export_name=manifest.renderer.export_name,
            )
        PluginManagerService._validate_backend_contract(
            backend_source=backend_source,
            class_name=manifest.service.class_name,
        )
        PluginManagerService._validate_config_schema(package["config_schema"])
        return manifest

    @staticmethod
    def _validate_blueprint_contract(blueprint_payload: Any, *, widget_id: str) -> None:
        if not isinstance(blueprint_payload, dict):
            raise ValueError("blueprint is required for blueprint renderer packages")
        blueprint = validate_blueprint(blueprint_payload)
        if blueprint.widget_id != widget_id:
            raise ValueError("view.blueprint.json widget_id must match manifest id")
        collect_binding_paths(blueprint)

    @staticmethod
    def _validate_renderer_contract(*, renderer_source: str, export_name: str) -> None:
        export_patterns = (
            rf"export\s+function\s+{re.escape(export_name)}\s*\(",
            rf"export\s+async\s+function\s+{re.escape(export_name)}\s*\(",
            rf"export\s+(?:const|let|var)\s+{re.escape(export_name)}\s*=",
            rf"export\s+class\s+{re.escape(export_name)}\b",
        )
        if not any(re.search(pattern, renderer_source) for pattern in export_patterns):
            raise ValueError(f"renderer.tsx must export '{export_name}'")

    @staticmethod
    def _validate_backend_contract(*, backend_source: str, class_name: str) -> None:
        try:
            tree = ast.parse(backend_source)
        except SyntaxError as exc:
            raise ValueError(f"backend.py has invalid syntax: {exc.msg}") from exc
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name != class_name:
                continue
            base_names = {_base_name(base) for base in node.bases}
            if "BaseWidgetService" not in base_names:
                raise ValueError(f"backend.py class '{class_name}' must inherit BaseWidgetService")
            return
        raise ValueError(f"backend.py must define service class '{class_name}'")

    @staticmethod
    def _validate_config_schema(config_schema: Any) -> None:
        if not isinstance(config_schema, dict):
            raise ValueError("config_schema must be a JSON object")
        schema_type = config_schema.get("type")
        if schema_type is not None and schema_type != "object":
            raise ValueError("config_schema type must be 'object' when specified")


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""
