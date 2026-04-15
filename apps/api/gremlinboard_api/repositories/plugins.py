from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gremlinboard_api.models.tables import WidgetPluginRecord, WidgetPluginVersionRecord
from gremlinboard_api.schemas.contracts import WidgetPluginRead, WidgetPluginVersionRead


class PluginRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_plugin(self, widget_id: str) -> WidgetPluginRecord | None:
        return await self.session.get(WidgetPluginRecord, widget_id)

    async def list_plugins(self) -> list[WidgetPluginRecord]:
        result = await self.session.execute(select(WidgetPluginRecord).order_by(WidgetPluginRecord.widget_id.asc()))
        return list(result.scalars())

    async def upsert_plugin(
        self,
        *,
        widget_id: str,
        version: str,
        enabled: bool,
        installed: bool,
        is_core: bool,
        source_type: str,
        source_ref: str | None,
        last_error: str | None = None,
    ) -> WidgetPluginRecord:
        record = await self.get_plugin(widget_id)
        if record is None:
            record = WidgetPluginRecord(
                widget_id=widget_id,
                version=version,
                enabled=enabled,
                installed=installed,
                is_core=is_core,
                source_type=source_type,
                source_ref=source_ref,
                last_error=last_error,
            )
            self.session.add(record)
        else:
            record.version = version
            record.enabled = enabled
            record.installed = installed
            record.is_core = is_core
            record.source_type = source_type
            record.source_ref = source_ref
            record.last_error = last_error
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def create_version_snapshot(
        self,
        *,
        widget_id: str,
        version: str,
        package: dict[str, Any],
        is_rollback: bool = False,
    ) -> WidgetPluginVersionRecord:
        record = WidgetPluginVersionRecord(
            widget_id=widget_id,
            version=version,
            package_json=json.dumps(package),
            is_rollback=is_rollback,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_version(self, widget_id: str, version: str) -> WidgetPluginVersionRecord | None:
        result = await self.session.execute(
            select(WidgetPluginVersionRecord).where(
                WidgetPluginVersionRecord.widget_id == widget_id,
                WidgetPluginVersionRecord.version == version,
            )
            .order_by(WidgetPluginVersionRecord.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_versions(self, widget_id: str) -> list[WidgetPluginVersionRecord]:
        result = await self.session.execute(
            select(WidgetPluginVersionRecord)
            .where(WidgetPluginVersionRecord.widget_id == widget_id)
            .order_by(WidgetPluginVersionRecord.created_at.desc())
        )
        return list(result.scalars())


def serialize_plugin(record: WidgetPluginRecord) -> WidgetPluginRead:
    return WidgetPluginRead(
        widget_id=record.widget_id,
        version=record.version,
        enabled=record.enabled,
        installed=record.installed,
        is_core=record.is_core,
        source_type=record.source_type,
        source_ref=record.source_ref,
        installed_at=record.installed_at,
        updated_at=record.updated_at,
        last_error=record.last_error,
    )


def serialize_plugin_version(record: WidgetPluginVersionRecord) -> WidgetPluginVersionRead:
    return WidgetPluginVersionRead(
        widget_id=record.widget_id,
        version=record.version,
        created_at=record.created_at,
        is_rollback=record.is_rollback,
    )


def decode_version_package(record: WidgetPluginVersionRecord) -> dict[str, Any]:
    return json.loads(record.package_json)
