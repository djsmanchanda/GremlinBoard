from __future__ import annotations

import json
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
from gremlinboard_api.repositories.plugins import (
    PluginRepository,
    decode_version_package,
    serialize_plugin,
    serialize_plugin_version,
)
from gremlinboard_api.schemas.contracts import (
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
                await repository.upsert_plugin(
                    widget_id=entry.manifest.id,
                    version=entry.manifest.version,
                    enabled=existing.enabled if existing else True,
                    installed=True,
                    is_core=existing.is_core if existing else True,
                    source_type=existing.source_type if existing else "core",
                    source_ref=existing.source_ref if existing else str(entry.root_dir),
                    last_error=None,
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
        package = request.package.model_dump()
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
            await repository.create_version_snapshot(
                widget_id=manifest.id,
                version=manifest.version,
                package=package,
            )
            return serialize_plugin(record)

    async def update_widget(self, widget_id: str, request: WidgetPluginUpdateRequest) -> WidgetPluginRead:
        package = request.package.model_dump()
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
        return {
            "manifest": json.loads((widget_root / "manifest.json").read_text(encoding="utf-8")),
            "config_schema": json.loads((widget_root / "config.schema.json").read_text(encoding="utf-8")),
            "backend_source": (widget_root / "backend.py").read_text(encoding="utf-8"),
            "renderer_source": (widget_root / "renderer.tsx").read_text(encoding="utf-8"),
        }

    @staticmethod
    def _write_package(widget_root: Path, package: dict[str, Any], *, replace: bool = False) -> None:
        manifest = WidgetManifest.model_validate(package["manifest"]).model_dump(mode="json")
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
        (widget_root / "renderer.tsx").write_text(package["renderer_source"], encoding="utf-8")
        (widget_root / "__init__.py").write_text('"""Widget package."""\n', encoding="utf-8")

    @staticmethod
    def _validate_package(package: dict[str, Any]) -> WidgetManifest:
        validate_widget_manifest_paths(package["manifest"])
        manifest = WidgetManifest.model_validate(package["manifest"])
        validate_widget_package_source(
            backend_source=str(package["backend_source"]),
            renderer_source=str(package["renderer_source"]),
            widget_id=manifest.id,
        )
        PluginManagerService._validate_renderer_contract(
            renderer_source=str(package["renderer_source"]),
            export_name=manifest.renderer.export_name,
        )
        return manifest

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
