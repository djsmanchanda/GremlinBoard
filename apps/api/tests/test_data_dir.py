from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import gremlinboard_api.main as main_module
from gremlinboard_api.config import Settings, default_data_dir, settings
from gremlinboard_api.db import Base
from gremlinboard_api.registry.loader import load_registry
from gremlinboard_api.runtime.events import EventBus
from gremlinboard_api.runtime.manager import RuntimeManager
from gremlinboard_api.schemas.contracts import WidgetPackagePayload, WidgetPluginInstallRequest
from gremlinboard_api.services.plugin_manager import PluginManagerService


# ---------------------------------------------------------------------------
# default_data_dir() per-platform resolution
# ---------------------------------------------------------------------------


def test_default_data_dir_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gremlinboard_api.config.sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")

    assert default_data_dir() == Path(r"C:\Users\test\AppData\Local") / "GremlinBoard"


def test_default_data_dir_windows_without_localappdata_falls_back_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gremlinboard_api.config.sys.platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    assert default_data_dir() == Path.home() / "AppData" / "Local" / "GremlinBoard"


def test_default_data_dir_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gremlinboard_api.config.sys.platform", "darwin")

    assert default_data_dir() == Path.home() / "Library" / "Application Support" / "GremlinBoard"


def test_default_data_dir_linux_uses_xdg_data_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gremlinboard_api.config.sys.platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/tmp/custom-xdg")

    assert default_data_dir() == Path("/tmp/custom-xdg") / "gremlinboard"


def test_default_data_dir_linux_falls_back_without_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gremlinboard_api.config.sys.platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    assert default_data_dir() == Path.home() / ".local" / "share" / "gremlinboard"


def test_settings_derives_database_url_and_user_widgets_dir_from_data_dir(tmp_path: Path) -> None:
    # The repo ships a root `.env` that pins GREMLINBOARD_DATABASE_URL for local
    # dev; disable dotenv loading here so this test exercises pure default
    # resolution instead of that repo-local override.
    resolved = Settings(data_dir=tmp_path, _env_file=None)

    assert resolved.database_url == f"sqlite+aiosqlite:///{(tmp_path / 'gremlinboard.db').as_posix()}"
    assert resolved.user_widgets_dir == tmp_path / "widgets"


def test_settings_explicit_database_url_env_override_wins_over_data_dir(tmp_path: Path) -> None:
    explicit_url = f"sqlite+aiosqlite:///{(tmp_path / 'elsewhere.db').as_posix()}"
    resolved = Settings(data_dir=tmp_path, database_url=explicit_url, _env_file=None)

    assert resolved.database_url == explicit_url
    # user_widgets_dir is independent and still derives from data_dir.
    assert resolved.user_widgets_dir == tmp_path / "widgets"


# ---------------------------------------------------------------------------
# Plugin installs write to the user widgets root, not the core root
# ---------------------------------------------------------------------------


def _sample_package(widget_id: str) -> dict:
    return {
        "manifest": {
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
        },
        "config_schema": {"type": "object", "properties": {}},
        "backend_source": (
            "from gremlinboard_api.runtime.base import BaseWidgetService\n\n\n"
            "class Service(BaseWidgetService):\n    pass\n"
        ),
        "renderer_source": "export function Renderer() { return null; }\n",
    }


@pytest.mark.asyncio
async def test_install_widget_writes_package_to_user_widgets_dir_only(tmp_path: Path) -> None:
    core_dir = tmp_path / "core" / "widgets"
    user_dir = tmp_path / "user" / "widgets"
    core_dir.mkdir(parents=True)
    user_dir.mkdir(parents=True)

    database_path = tmp_path / "install.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    registry = load_registry(core_dir, user_dir)
    plugin_manager = PluginManagerService(session_factory=session_factory, widgets_dir=user_dir, registry=registry)

    package = _sample_package("installed_widget")
    request = WidgetPluginInstallRequest(package=WidgetPackagePayload(**package))
    record = await plugin_manager.install_widget(request)

    assert record.is_core is False
    assert (user_dir / "installed_widget" / "manifest.json").exists()
    assert not (core_dir / "installed_widget").exists()
    assert registry.get("installed_widget").root_dir == user_dir / "installed_widget"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Auto-migration: legacy DB copy + non-core widget dir move
# ---------------------------------------------------------------------------


def test_migrate_legacy_user_data_copies_db_and_moves_generated_widgets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_repo_root = tmp_path / "repo"
    legacy_data_dir = fake_repo_root / "data"
    legacy_data_dir.mkdir(parents=True)
    legacy_db_path = legacy_data_dir / "gremlinboard.db"

    connection = sqlite3.connect(str(legacy_db_path))
    connection.execute("CREATE TABLE widget_plugins (widget_id TEXT PRIMARY KEY, is_core INTEGER)")
    connection.execute("INSERT INTO widget_plugins VALUES ('core_widget', 1)")
    connection.execute("INSERT INTO widget_plugins VALUES ('generated_widget', 0)")
    connection.commit()
    connection.close()

    repo_widgets_dir = fake_repo_root / "widgets"
    (repo_widgets_dir / "core_widget").mkdir(parents=True)
    (repo_widgets_dir / "core_widget" / "manifest.json").write_text("{}", encoding="utf-8")
    (repo_widgets_dir / "generated_widget").mkdir(parents=True)
    (repo_widgets_dir / "generated_widget" / "manifest.json").write_text("{}", encoding="utf-8")
    (repo_widgets_dir / "unknown_widget").mkdir(parents=True)
    (repo_widgets_dir / "unknown_widget" / "manifest.json").write_text("{}", encoding="utf-8")

    new_data_dir = tmp_path / "platform-data"
    new_user_widgets_dir = new_data_dir / "widgets"
    new_database_url = f"sqlite+aiosqlite:///{(new_data_dir / 'gremlinboard.db').as_posix()}"

    monkeypatch.setattr(main_module, "ROOT_DIR", fake_repo_root)
    monkeypatch.setattr(settings, "data_dir", new_data_dir)
    monkeypatch.setattr(settings, "user_widgets_dir", new_user_widgets_dir)
    monkeypatch.setattr(settings, "widgets_dir", repo_widgets_dir)
    monkeypatch.setattr(settings, "database_url", new_database_url)

    main_module.migrate_legacy_user_data()

    new_db_path = new_data_dir / "gremlinboard.db"
    assert new_db_path.exists()
    assert legacy_db_path.exists(), "legacy db must be copied, not moved"

    assert (new_user_widgets_dir / "generated_widget").exists()
    assert not (repo_widgets_dir / "generated_widget").exists()

    assert (repo_widgets_dir / "core_widget").exists(), "core widgets stay in the repo"
    assert (repo_widgets_dir / "unknown_widget").exists(), "widgets with no DB record are left untouched"
    assert not (new_user_widgets_dir / "unknown_widget").exists()

    # Idempotent: running again must not error or duplicate/lose anything.
    main_module.migrate_legacy_user_data()
    assert (new_user_widgets_dir / "generated_widget").exists()
    assert (repo_widgets_dir / "core_widget").exists()
    assert new_db_path.exists()


def test_migrate_legacy_user_data_is_a_no_op_without_a_legacy_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_repo_root = tmp_path / "repo"
    (fake_repo_root / "data").mkdir(parents=True)

    new_data_dir = tmp_path / "platform-data"
    new_user_widgets_dir = new_data_dir / "widgets"
    new_database_url = f"sqlite+aiosqlite:///{(new_data_dir / 'gremlinboard.db').as_posix()}"

    monkeypatch.setattr(main_module, "ROOT_DIR", fake_repo_root)
    monkeypatch.setattr(settings, "data_dir", new_data_dir)
    monkeypatch.setattr(settings, "user_widgets_dir", new_user_widgets_dir)
    monkeypatch.setattr(settings, "widgets_dir", fake_repo_root / "widgets")
    monkeypatch.setattr(settings, "database_url", new_database_url)

    main_module.migrate_legacy_user_data()

    assert new_data_dir.exists()
    assert new_user_widgets_dir.exists()
    assert not (new_data_dir / "gremlinboard.db").exists()


# ---------------------------------------------------------------------------
# Process host command uses the per-widget root, not the registry's core root
# ---------------------------------------------------------------------------


def _write_process_host_widget(root: Path, widget_id: str) -> None:
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


def test_python_process_host_command_uses_per_widget_root(tmp_path: Path) -> None:
    core_parent = tmp_path / "core"
    user_parent = tmp_path / "user"
    core_dir = core_parent / "widgets"
    user_dir = user_parent / "widgets"
    _write_process_host_widget(core_dir, "core_widget")
    _write_process_host_widget(user_dir, "generated_widget")

    registry = load_registry(core_dir, user_dir)
    manager = RuntimeManager(
        session_factory=None,  # type: ignore[arg-type]
        registry=registry,
        event_bus=EventBus(),
        board_id="board",
    )

    core_command = manager._python_process_host_command(registry.get("core_widget").manifest)
    generated_command = manager._python_process_host_command(registry.get("generated_widget").manifest)

    assert core_command[5] == str(core_parent.resolve())
    assert generated_command[5] == str(user_parent.resolve())
    assert core_command[5] != generated_command[5]
