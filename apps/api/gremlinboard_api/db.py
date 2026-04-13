from __future__ import annotations

from collections.abc import AsyncIterator

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
    from gremlinboard_api.models.tables import BoardRecord, StagedWidgetSpecRecord, WidgetInstanceRecord

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
