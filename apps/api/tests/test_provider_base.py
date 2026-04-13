from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from gremlinboard_api.providers.base import ExternalDataProvider
from gremlinboard_api.providers.cache import ResponseCache
from gremlinboard_api.providers.models import ProviderRequest


@dataclass
class DummySecrets:
    def resolve(self, provider_id: str):
        class Credentials:
            def get(self, key: str):
                return None

        return Credentials()


@dataclass
class DummyRuntime:
    cache: ResponseCache
    secrets: DummySecrets
    client: object = object()


class SuccessThenCacheProvider(ExternalDataProvider):
    provider_id = "dummy"
    label = "Dummy"
    default_ttl_seconds = 60

    def __init__(self, runtime):
        super().__init__(runtime)
        self.calls = 0

    async def fetch_remote(self, *, query: dict[str, object]) -> dict[str, object]:
        self.calls += 1
        return {
            "data": {"value": self.calls},
            "source_url": "https://example.test",
        }


class FallbackProvider(ExternalDataProvider):
    provider_id = "dummy-fallback"
    label = "Dummy Fallback"

    async def fetch_remote(self, *, query: dict[str, object]) -> dict[str, object]:
        raise ValueError("boom")

    def fallback_response(self, *, query, error):
        return {"value": "fallback", "error": str(error)}


@pytest.mark.asyncio
async def test_provider_fetch_uses_cache_after_first_success() -> None:
    runtime = DummyRuntime(cache=ResponseCache(), secrets=DummySecrets())
    provider = SuccessThenCacheProvider(runtime)
    request = ProviderRequest(cache_namespace="widget-1", query={"topic": "ops"})

    first = await provider.fetch(request=request)
    second = await provider.fetch(request=request)

    assert first.data == {"value": 1}
    assert second.data == {"value": 1}
    assert second.cached is True
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_provider_fetch_uses_fallback_on_failure() -> None:
    runtime = DummyRuntime(cache=ResponseCache(), secrets=DummySecrets())
    provider = FallbackProvider(runtime)

    result = await provider.fetch(request=ProviderRequest(cache_namespace="widget-2", query={"topic": "ops"}))

    assert result.fallback is True
    assert result.data["value"] == "fallback"
    assert result.health.status == "degraded"
    assert result.fetched_at <= datetime.now(timezone.utc)
