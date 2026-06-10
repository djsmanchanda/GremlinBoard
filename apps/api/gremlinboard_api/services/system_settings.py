from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gremlinboard_api.repositories.platform import PlatformRepository, decode_setting, serialize_credential
from gremlinboard_api.schemas.contracts import (
    AIProviderSettingsSection,
    ApiCredentialRead,
    ApiCredentialUpsertRequest,
    AppSettingsSection,
    AppearanceSettingsSection,
    RuntimeSettingsSection,
    SystemSettingsRead,
    SystemSettingsUpdateRequest,
)


DEFAULT_SYSTEM_SETTINGS = {
    "runtime": RuntimeSettingsSection().model_dump(mode="json"),
    "appearance": AppearanceSettingsSection().model_dump(mode="json"),
    "ai": AIProviderSettingsSection().model_dump(mode="json"),
    "app": AppSettingsSection().model_dump(mode="json"),
}

MIN_MONITOR_INTERVAL_SECONDS = 15


class SystemSettingsService:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def ensure_defaults(self, *, user_id: str | None) -> None:
        async with self.session_factory() as session:
            repository = PlatformRepository(session)
            for section, payload in DEFAULT_SYSTEM_SETTINGS.items():
                existing = await repository.get_setting(section)
                if existing is None:
                    await repository.upsert_setting(section=section, data=payload, updated_by_user_id=user_id)

    async def read(self) -> SystemSettingsRead:
        async with self.session_factory() as session:
            repository = PlatformRepository(session)
            payloads = {record.section: decode_setting(record) for record in await repository.list_settings()}
        merged = {key: payloads.get(key, value) for key, value in DEFAULT_SYSTEM_SETTINGS.items()}
        merged["runtime"] = _normalize_runtime_settings(merged["runtime"])
        return SystemSettingsRead(
            runtime=RuntimeSettingsSection.model_validate(merged["runtime"]),
            appearance=AppearanceSettingsSection.model_validate(merged["appearance"]),
            ai=AIProviderSettingsSection.model_validate(merged["ai"]),
            app=AppSettingsSection.model_validate(merged["app"]),
        )

    async def update(self, payload: SystemSettingsUpdateRequest, *, user_id: str | None) -> SystemSettingsRead:
        current = await self.read()
        updates: dict[str, Any] = current.model_dump(mode="json")
        for section in ("runtime", "appearance", "ai", "app"):
            value = getattr(payload, section)
            if value is not None:
                updates[section] = value.model_dump(mode="json")
        updates["runtime"] = _normalize_runtime_settings(updates["runtime"])
        async with self.session_factory() as session:
            repository = PlatformRepository(session)
            for section, value in updates.items():
                await repository.upsert_setting(section=section, data=value, updated_by_user_id=user_id)
        return await self.read()

    async def list_credentials(self) -> list[ApiCredentialRead]:
        async with self.session_factory() as session:
            repository = PlatformRepository(session)
            return [serialize_credential(record) for record in await repository.list_credentials()]

    async def list_credential_secrets_by_provider(self) -> dict[str, str]:
        async with self.session_factory() as session:
            repository = PlatformRepository(session)
            credentials = await repository.list_credentials()
            return {record.provider: record.value_secret for record in credentials}

    async def upsert_credential(
        self,
        payload: ApiCredentialUpsertRequest,
        *,
        credential_id: str | None,
        user_id: str | None,
    ) -> ApiCredentialRead:
        async with self.session_factory() as session:
            repository = PlatformRepository(session)
            record = await repository.upsert_credential(
                credential_id=credential_id,
                provider=payload.provider,
                label=payload.label,
                value_secret=payload.value,
                updated_by_user_id=user_id,
            )
            return serialize_credential(record)

    async def delete_credential(self, credential_id: str) -> None:
        async with self.session_factory() as session:
            repository = PlatformRepository(session)
            await repository.delete_credential(credential_id)


def _normalize_runtime_settings(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    value = normalized.get("monitor_interval_seconds", RuntimeSettingsSection().monitor_interval_seconds)
    if not isinstance(value, int) or isinstance(value, bool):
        value = RuntimeSettingsSection().monitor_interval_seconds
    normalized["monitor_interval_seconds"] = max(value, MIN_MONITOR_INTERVAL_SECONDS)
    return normalized
