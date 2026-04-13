from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from gremlinboard_api.config import settings


class Base(DeclarativeBase):
    pass


engine: AsyncEngine = create_async_engine(settings.database_url, future=True)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from gremlinboard_api.models.tables import (
        BoardRecord,
        GenerationArtifactRecord,
        GenerationJobLogRecord,
        GenerationJobRecord,
        RuntimeLogRecord,
        StagedWidgetSpecRecord,
        WidgetInstanceRecord,
        WidgetPluginRecord,
        WidgetPluginVersionRecord,
    )

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await _run_migrations(connection)


async def _run_migrations(connection) -> None:
    await _ensure_columns(
        connection,
        "widget_instances",
        {
            "service_started_at": "ALTER TABLE widget_instances ADD COLUMN service_started_at DATETIME",
            "service_uptime_seconds": "ALTER TABLE widget_instances ADD COLUMN service_uptime_seconds INTEGER NOT NULL DEFAULT 0",
            "restart_count": "ALTER TABLE widget_instances ADD COLUMN restart_count INTEGER NOT NULL DEFAULT 0",
            "consecutive_failures": "ALTER TABLE widget_instances ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0",
        },
    )


async def _ensure_columns(connection, table_name: str, ddl_by_column: dict[str, str]) -> None:
    result = await connection.execute(text(f"PRAGMA table_info({table_name})"))
    existing_columns = {row[1] for row in result.fetchall()}
    for column_name, ddl in ddl_by_column.items():
        if column_name not in existing_columns:
            await connection.execute(text(ddl))
