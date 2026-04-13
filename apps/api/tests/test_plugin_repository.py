from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gremlinboard_api.db import Base
from gremlinboard_api.repositories.plugins import PluginRepository


@pytest.mark.asyncio
async def test_plugin_repository_tracks_versions() -> None:
    database_path = Path("data") / f"plugin-test-{uuid4().hex}.db"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database_url = f"sqlite+aiosqlite:///{database_path.resolve().as_posix()}"
    engine = create_async_engine(database_url, future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        repository = PluginRepository(session)
        plugin = await repository.upsert_plugin(
            widget_id="custom_widget",
            version="1.0.0",
            enabled=True,
            installed=True,
            is_core=False,
            source_type="manual",
            source_ref="widgets/custom_widget",
        )
        await repository.create_version_snapshot(
            widget_id="custom_widget",
            version="1.0.0",
            package={"manifest": {"id": "custom_widget", "version": "1.0.0"}},
        )
        versions = await repository.list_versions("custom_widget")

        assert plugin.widget_id == "custom_widget"
        assert plugin.version == "1.0.0"
        assert len(versions) == 1
        assert versions[0].version == "1.0.0"

    await engine.dispose()
    if database_path.exists():
        database_path.unlink()
