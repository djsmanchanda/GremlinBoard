from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gremlinboard_api.ai.providers import AIProvider, ClaudeProvider, CodexProvider
from gremlinboard_api.models.tables import StagedWidgetSpecRecord
from gremlinboard_api.schemas.contracts import AIProviderRead, GenerationPipelinePreviewRead


class GenerationPipelineService:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.providers: dict[str, AIProvider] = {
            "codex": CodexProvider(),
            "claude": ClaudeProvider(),
        }

    async def list_providers(self) -> list[AIProviderRead]:
        items: list[AIProviderRead] = []
        for provider in self.providers.values():
            health = await provider.health()
            items.append(
                AIProviderRead(
                    provider_id=provider.provider_id,
                    label=provider.label,
                    status=str(health.get("status", "unknown")),
                    supports_codegen=provider.supports_codegen,
                    supports_review=provider.supports_review,
                )
            )
        return items

    async def preview_generation(self, *, provider_id: str, stage_id: str) -> GenerationPipelinePreviewRead:
        provider = self.providers.get(provider_id)
        if provider is None:
            raise ValueError(f"unknown provider '{provider_id}'")
        async with self.session_factory() as session:
            record = await session.get(StagedWidgetSpecRecord, stage_id)
            if record is None:
                raise ValueError(f"unknown spec stage '{stage_id}'")
            spec = json.loads(record.spec_json)
        plan = await provider.build_generation_plan(widget_spec=spec, stage_id=stage_id)
        return GenerationPipelinePreviewRead(
            stage_id=stage_id,
            provider_id=provider_id,
            steps=plan["steps"],
            install_blocked=True,
        )
