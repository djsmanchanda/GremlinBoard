from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from gremlinboard_api.config import Settings
from gremlinboard_api.providers.base import ExternalDataProvider
from gremlinboard_api.providers.cache import ResponseCache
from gremlinboard_api.providers.models import ProviderRequest
from gremlinboard_api.providers.registry import ProviderRuntime


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


class SlowSuccessProvider(SuccessThenCacheProvider):
    async def fetch_remote(self, *, query: dict[str, object]) -> dict[str, object]:
        await asyncio.sleep(0.05)
        return await super().fetch_remote(query=query)


class FallbackProvider(ExternalDataProvider):
    provider_id = "dummy-fallback"
    label = "Dummy Fallback"
    max_retries = 0

    def __init__(self, runtime):
        super().__init__(runtime)
        self.calls = 0

    async def fetch_remote(self, *, query: dict[str, object]) -> dict[str, object]:
        self.calls += 1
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


@pytest.mark.asyncio
async def test_provider_runtime_coalesces_identical_inflight_requests_across_cache_namespaces() -> None:
    runtime = ProviderRuntime(Settings())
    provider = SlowSuccessProvider(runtime)
    try:
        first_request = ProviderRequest(cache_namespace="widget-1", query={"topic": "ops"})
        second_request = ProviderRequest(cache_namespace="widget-2", query={"topic": "ops"})

        first, second = await asyncio.gather(
            provider.fetch(request=first_request),
            provider.fetch(request=second_request),
        )
        cached_second = await provider.fetch(request=second_request)
        snapshot = await runtime.activity_snapshot()

        assert first.data == {"value": 1}
        assert second.data == {"value": 1}
        assert cached_second.cached is True
        assert provider.calls == 1
        assert snapshot["coordination"]["coalesced_request_count"] == 1
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_provider_cooldown_suppresses_remote_calls_after_repeated_failures() -> None:
    runtime = ProviderRuntime(Settings())
    provider = FallbackProvider(runtime)
    request = ProviderRequest(cache_namespace="widget-3", query={"topic": "ops"})
    try:
        await provider.fetch(request=request)
        await provider.fetch(request=request)
        result = await provider.fetch(request=request)
        snapshot = await runtime.activity_snapshot()
        activity = snapshot["providers"][0]

        assert result.fallback is True
        assert provider.calls == 2
        assert activity["cooldown_skips"] == 1
        assert activity["cooldown_until"] is not None
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_provider_cooldown_uses_each_widget_stale_cache_without_coalescing() -> None:
    runtime = ProviderRuntime(Settings())
    provider = FallbackProvider(runtime)
    first_request = ProviderRequest(cache_namespace="widget-a", query={"topic": "ops"})
    second_request = ProviderRequest(cache_namespace="widget-b", query={"topic": "ops"})
    try:
        await runtime.cache.set(
            provider._cache_key(second_request) or "",
            {
                "data": {"value": "stale-b"},
                "source_url": "https://example.test/stale",
                "fetched_at": datetime.now(timezone.utc),
            },
            ttl_seconds=1,
        )
        runtime.cache._entries[provider._cache_key(second_request) or ""].expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )

        await provider.fetch(request=first_request)
        await provider.fetch(request=first_request)
        first, second = await asyncio.gather(
            provider.fetch(request=first_request),
            provider.fetch(request=second_request),
        )

        assert first.fallback is True
        assert first.stale is False
        assert second.stale is True
        assert second.data == {"value": "stale-b"}
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_response_cache_drops_entries_after_stale_retention_window() -> None:
    cache = ResponseCache(stale_retention_seconds=0)
    await cache.set("widget:provider:query", {"value": 1}, ttl_seconds=60)
    cache._entries["widget:provider:query"].discard_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    assert await cache.peek("widget:provider:query") is None
    assert (await cache.stats()).entry_count == 0
