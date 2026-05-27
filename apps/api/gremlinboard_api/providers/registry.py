from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from gremlinboard_api.config import Settings
from gremlinboard_api.providers.adapters import (
    CricketDataProvider,
    FootballDataProvider,
    HackerNewsProvider,
    NewsApiProvider,
    OpenF1Provider,
    RedditProvider,
    RssNewsProvider,
    XSearchProvider,
)
from gremlinboard_api.providers.cache import ResponseCache
from gremlinboard_api.providers.secrets import SecretResolver


@dataclass(slots=True)
class ProviderActivity:
    provider_id: str
    active_requests: int = 0
    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    stale_fallbacks: int = 0
    fallback_responses: int = 0
    errors: int = 0
    last_status: str = "unknown"
    last_error: str | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None


class ProviderRuntime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache = ResponseCache()
        self.secrets = SecretResolver(settings)
        self._activity: dict[str, ProviderActivity] = {}
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.external_http_timeout_seconds),
            headers={
                "User-Agent": settings.provider_user_agent,
                "Accept": "application/json, application/xml;q=0.9, text/xml;q=0.8",
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def invalidate_namespace(self, namespace: str) -> None:
        await self.cache.invalidate_prefix(namespace)

    def record_provider_started(self, provider_id: str) -> None:
        activity = self._activity.setdefault(provider_id, ProviderActivity(provider_id=provider_id))
        activity.active_requests += 1
        activity.total_requests += 1
        activity.last_started_at = datetime.now(timezone.utc)

    def record_provider_finished(
        self,
        provider_id: str,
        *,
        status: str,
        cache_status: str = "none",
        fallback_used: bool = False,
        error: str | None = None,
    ) -> None:
        activity = self._activity.setdefault(provider_id, ProviderActivity(provider_id=provider_id))
        activity.active_requests = max(activity.active_requests - 1, 0)
        activity.last_status = status
        activity.last_error = error
        activity.last_finished_at = datetime.now(timezone.utc)
        if cache_status == "hit":
            activity.cache_hits += 1
        elif cache_status in {"miss", "none"}:
            activity.cache_misses += 1
        elif cache_status == "stale":
            activity.stale_fallbacks += 1
        elif cache_status == "fallback":
            activity.fallback_responses += 1
        if fallback_used and cache_status not in {"stale", "fallback"}:
            activity.fallback_responses += 1
        if error is not None or status == "error":
            activity.errors += 1

    def record_provider_aborted(self, provider_id: str, error: str) -> None:
        activity = self._activity.setdefault(provider_id, ProviderActivity(provider_id=provider_id))
        activity.active_requests = max(activity.active_requests - 1, 0)
        activity.last_status = "error"
        activity.last_error = error
        activity.last_finished_at = datetime.now(timezone.utc)
        activity.errors += 1

    async def activity_snapshot(self) -> dict[str, Any]:
        cache_stats = await self.cache.stats()
        return {
            "providers": [
                {
                    "provider_id": activity.provider_id,
                    "active_requests": activity.active_requests,
                    "total_requests": activity.total_requests,
                    "cache_hits": activity.cache_hits,
                    "cache_misses": activity.cache_misses,
                    "stale_fallbacks": activity.stale_fallbacks,
                    "fallback_responses": activity.fallback_responses,
                    "errors": activity.errors,
                    "last_status": activity.last_status,
                    "last_error": activity.last_error,
                    "last_started_at": activity.last_started_at,
                    "last_finished_at": activity.last_finished_at,
                }
                for activity in sorted(self._activity.values(), key=lambda item: item.provider_id)
            ],
            "cache": {
                "entry_count": cache_stats.entry_count,
                "max_entries": cache_stats.max_entries,
                "expired_entry_count": cache_stats.expired_entry_count,
                "namespace_counts": cache_stats.namespace_counts,
            },
        }


class ExternalProviderRegistry:
    def __init__(self, runtime: ProviderRuntime):
        self.runtime = runtime

    def create_sports_provider(self, provider_id: str):
        mapping = {
            "cricketdata": CricketDataProvider,
            "football-data": FootballDataProvider,
            "openf1": OpenF1Provider,
        }
        provider_class = mapping.get(provider_id)
        if provider_class is None:
            raise KeyError(f"unsupported sports provider '{provider_id}'")
        return provider_class(self.runtime)

    def create_news_provider(self, provider_id: str):
        mapping = {
            "newsapi": NewsApiProvider,
            "rss": RssNewsProvider,
        }
        provider_class = mapping.get(provider_id)
        if provider_class is None:
            raise KeyError(f"unsupported news provider '{provider_id}'")
        return provider_class(self.runtime)

    def create_trending_provider(self, provider_id: str):
        mapping = {
            "reddit": RedditProvider,
            "hackernews": HackerNewsProvider,
            "x": XSearchProvider,
        }
        provider_class = mapping.get(provider_id)
        if provider_class is None:
            raise KeyError(f"unsupported trending provider '{provider_id}'")
        return provider_class(self.runtime)
