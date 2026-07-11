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
    # Import models so SQLAlchemy registers table metadata before create_all.
    import gremlinboard_api.models.tables  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await _run_migrations(connection)


async def _run_migrations(connection) -> None:
    await _ensure_columns(
        connection,
        "boards",
        {
            "owner_user_id": "ALTER TABLE boards ADD COLUMN owner_user_id VARCHAR(64)",
        },
    )
    await _ensure_columns(
        connection,
        "widget_instances",
        {
            "owner_user_id": "ALTER TABLE widget_instances ADD COLUMN owner_user_id VARCHAR(64)",
            "service_started_at": "ALTER TABLE widget_instances ADD COLUMN service_started_at DATETIME",
            "service_uptime_seconds": "ALTER TABLE widget_instances ADD COLUMN service_uptime_seconds INTEGER NOT NULL DEFAULT 0",
            "restart_count": "ALTER TABLE widget_instances ADD COLUMN restart_count INTEGER NOT NULL DEFAULT 0",
            "consecutive_failures": "ALTER TABLE widget_instances ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0",
        },
    )
    await _ensure_columns(
        connection,
        "generation_jobs",
        {
            "progress": "ALTER TABLE generation_jobs ADD COLUMN progress INTEGER NOT NULL DEFAULT 0",
            "queued_input_json": "ALTER TABLE generation_jobs ADD COLUMN queued_input_json TEXT",
            "generation_mode": "ALTER TABLE generation_jobs ADD COLUMN generation_mode VARCHAR(32)",
            "model_id": "ALTER TABLE generation_jobs ADD COLUMN model_id VARCHAR(128)",
            "token_usage_json": "ALTER TABLE generation_jobs ADD COLUMN token_usage_json TEXT",
        },
    )


async def _ensure_columns(connection, table_name: str, ddl_by_column: dict[str, str]) -> None:
    result = await connection.execute(text(f"PRAGMA table_info({table_name})"))
    existing_columns = {row[1] for row in result.fetchall()}
    for column_name, ddl in ddl_by_column.items():
        if column_name not in existing_columns:
            await connection.execute(text(ddl))
