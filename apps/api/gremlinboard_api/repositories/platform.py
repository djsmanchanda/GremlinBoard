from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from gremlinboard_api.models.tables import (
    ApiCredentialRecord,
    RuntimeMetricRecord,
    SessionRecord,
    SystemSettingsRecord,
    UserRecord,
)
from gremlinboard_api.schemas.contracts import (
    ApiCredentialRead,
    RuntimeMetricRead,
    SessionRead,
    UserRead,
)


class PlatformRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user(self, user_id: str) -> UserRecord | None:
        return await self.session.get(UserRecord, user_id)

    async def get_user_by_email(self, email: str) -> UserRecord | None:
        result = await self.session.execute(select(UserRecord).where(UserRecord.email == email))
        return result.scalar_one_or_none()

    async def upsert_user(
        self,
        *,
        user_id: str,
        email: str,
        display_name: str,
        role: str,
        is_active: bool = True,
    ) -> UserRecord:
        record = await self.get_user(user_id)
        if record is None:
            record = UserRecord(
                id=user_id,
                email=email,
                display_name=display_name,
                role=role,
                is_active=is_active,
            )
            self.session.add(record)
        else:
            record.email = email
            record.display_name = display_name
            record.role = role
            record.is_active = is_active
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_session(self, session_id: str) -> SessionRecord | None:
        return await self.session.get(SessionRecord, session_id)

    async def create_session(self, *, session_id: str, user_id: str, expires_at: datetime) -> SessionRecord:
        record = SessionRecord(id=session_id, user_id=user_id, expires_at=expires_at)
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def touch_session(self, record: SessionRecord, *, expires_at: datetime, status: str = "active") -> SessionRecord:
        record.last_seen_at = datetime.now(expires_at.tzinfo)
        record.expires_at = expires_at
        record.status = status
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_setting(self, section: str) -> SystemSettingsRecord | None:
        return await self.session.get(SystemSettingsRecord, section)

    async def upsert_setting(
        self,
        *,
        section: str,
        data: dict[str, Any],
        updated_by_user_id: str | None,
    ) -> SystemSettingsRecord:
        record = await self.get_setting(section)
        payload = json.dumps(data)
        if record is None:
            record = SystemSettingsRecord(
                section=section,
                data_json=payload,
                updated_by_user_id=updated_by_user_id,
            )
            self.session.add(record)
        else:
            record.data_json = payload
            record.updated_by_user_id = updated_by_user_id
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def list_settings(self) -> list[SystemSettingsRecord]:
        result = await self.session.execute(select(SystemSettingsRecord).order_by(SystemSettingsRecord.section.asc()))
        return list(result.scalars())

    async def list_credentials(self) -> list[ApiCredentialRecord]:
        result = await self.session.execute(select(ApiCredentialRecord).order_by(ApiCredentialRecord.provider.asc()))
        return list(result.scalars())

    async def get_credential(self, credential_id: str) -> ApiCredentialRecord | None:
        return await self.session.get(ApiCredentialRecord, credential_id)

    async def upsert_credential(
        self,
        *,
        credential_id: str | None,
        provider: str,
        label: str,
        value_secret: str,
        updated_by_user_id: str | None,
    ) -> ApiCredentialRecord:
        record = await self.get_credential(credential_id) if credential_id else None
        if record is None:
            record = ApiCredentialRecord(
                provider=provider,
                label=label,
                value_secret=value_secret,
                updated_by_user_id=updated_by_user_id,
            )
            self.session.add(record)
        else:
            record.provider = provider
            record.label = label
            record.value_secret = value_secret
            record.updated_by_user_id = updated_by_user_id
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def delete_credential(self, credential_id: str) -> None:
        record = await self.get_credential(credential_id)
        if record is None:
            return
        await self.session.delete(record)
        await self.session.commit()

    async def create_metric(
        self,
        *,
        scope_type: str,
        scope_id: str | None,
        metric_name: str,
        metric_value: int,
        tags: dict[str, Any],
    ) -> RuntimeMetricRecord:
        record = RuntimeMetricRecord(
            scope_type=scope_type,
            scope_id=scope_id,
            metric_name=metric_name,
            metric_value=metric_value,
            tags_json=json.dumps(tags),
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def create_metrics(self, items: list[dict[str, Any]]) -> None:
        for item in items:
            self.session.add(
                RuntimeMetricRecord(
                    scope_type=item["scope_type"],
                    scope_id=item.get("scope_id"),
                    metric_name=item["metric_name"],
                    metric_value=item["metric_value"],
                    tags_json=json.dumps(item.get("tags", {})),
                )
            )
        await self.session.commit()

    async def list_metrics(
        self,
        *,
        limit: int = 200,
        scope_type: str | None = None,
    ) -> list[RuntimeMetricRecord]:
        query = select(RuntimeMetricRecord).order_by(RuntimeMetricRecord.created_at.desc()).limit(limit)
        if scope_type is not None:
            query = query.where(RuntimeMetricRecord.scope_type == scope_type)
        result = await self.session.execute(query)
        return list(result.scalars())

    async def trim_metrics(self, *, keep_latest: int) -> None:
        metrics = await self.list_metrics(limit=keep_latest + 250)
        if len(metrics) <= keep_latest:
            return
        removable_ids = [record.id for record in metrics[keep_latest:]]
        await self.session.execute(delete(RuntimeMetricRecord).where(RuntimeMetricRecord.id.in_(removable_ids)))
        await self.session.commit()


def serialize_user(record: UserRecord) -> UserRead:
    return UserRead(
        id=record.id,
        email=record.email,
        display_name=record.display_name,
        role=record.role,
        is_active=record.is_active,
        created_at=record.created_at,
    )


def serialize_session(record: SessionRecord) -> SessionRead:
    return SessionRead(
        id=record.id,
        user_id=record.user_id,
        status=record.status,
        last_seen_at=record.last_seen_at,
        expires_at=record.expires_at,
        created_at=record.created_at,
    )


def serialize_credential(record: ApiCredentialRecord) -> ApiCredentialRead:
    return ApiCredentialRead(
        id=record.id,
        provider=record.provider,
        label=record.label,
        masked_value=_mask_secret(record.value_secret),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def serialize_metric(record: RuntimeMetricRecord) -> RuntimeMetricRead:
    return RuntimeMetricRead(
        scope_type=record.scope_type,
        scope_id=record.scope_id,
        metric_name=record.metric_name,
        metric_value=record.metric_value,
        tags=json.loads(record.tags_json or "{}"),
        created_at=record.created_at,
    )


def decode_setting(record: SystemSettingsRecord) -> dict[str, Any]:
    return json.loads(record.data_json or "{}")


def _mask_secret(value: str) -> str:
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}{'*' * (len(value) - 6)}{value[-3:]}"
