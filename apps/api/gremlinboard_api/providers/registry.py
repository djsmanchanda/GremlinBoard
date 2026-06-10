from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    coalesced_requests: int = 0
    cooldown_skips: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    stale_fallbacks: int = 0
    fallback_responses: int = 0
    errors: int = 0
    last_status: str = "unknown"
    last_error: str | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    consecutive_failures: int = 0
    cooldown_until: datetime | None = None


class ProviderRuntime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache = ResponseCache()
        self.secrets = SecretResolver(settings)
        self._activity: dict[str, ProviderActivity] = {}
        self._inflight: dict[str, asyncio.Task[Any]] = {}
        self._inflight_started_at: dict[str, datetime] = {}
        self._inflight_lock = asyncio.Lock()
        self.max_inflight_requests = 64
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

    async def coalesce_request(
        self,
        *,
        provider_id: str,
        key: str,
        factory,
    ) -> tuple[Any, bool]:
        task: asyncio.Task[Any] | None = None
        owner = False
        coalesced = False
        bypass_coalescing = False
        async with self._inflight_lock:
            task = self._inflight.get(key)
            if task is None or task.done():
                if len(self._inflight) >= self.max_inflight_requests:
                    bypass_coalescing = True
                else:
                    task = asyncio.create_task(factory())
                    self._inflight[key] = task
                    self._inflight_started_at[key] = datetime.now(timezone.utc)
                    owner = True
            else:
                activity = self._activity.setdefault(provider_id, ProviderActivity(provider_id=provider_id))
                activity.coalesced_requests += 1
                coalesced = True

        if bypass_coalescing:
            return await factory(), False
        if task is None:
            return await factory(), False

        try:
            return await task, coalesced
        finally:
            if owner:
                async with self._inflight_lock:
                    if self._inflight.get(key) is task:
                        self._inflight.pop(key, None)
                        self._inflight_started_at.pop(key, None)

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
        if error is not None or status == "error":
            activity.consecutive_failures += 1
            if activity.consecutive_failures >= 2:
                cooldown_seconds = min(60, 5 * (2 ** min(activity.consecutive_failures - 2, 3)))
                activity.cooldown_until = activity.last_finished_at + timedelta(seconds=cooldown_seconds)
        else:
            activity.consecutive_failures = 0
            activity.cooldown_until = None
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
        activity.consecutive_failures += 1
        if activity.consecutive_failures >= 2:
            cooldown_seconds = min(60, 5 * (2 ** min(activity.consecutive_failures - 2, 3)))
            activity.cooldown_until = activity.last_finished_at + timedelta(seconds=cooldown_seconds)
        activity.errors += 1

    def provider_cooldown_until(self, provider_id: str) -> datetime | None:
        activity = self._activity.setdefault(provider_id, ProviderActivity(provider_id=provider_id))
        if activity.cooldown_until is None:
            return None
        now = datetime.now(timezone.utc)
        if activity.cooldown_until <= now:
            activity.cooldown_until = None
            return None
        activity.cooldown_skips += 1
        return activity.cooldown_until

    def is_provider_cooling_down(self, provider_id: str) -> bool:
        activity = self._activity.setdefault(provider_id, ProviderActivity(provider_id=provider_id))
        if activity.cooldown_until is None:
            return False
        now = datetime.now(timezone.utc)
        if activity.cooldown_until <= now:
            activity.cooldown_until = None
            return False
        return True

    async def activity_snapshot(self) -> dict[str, Any]:
        cache_stats = await self.cache.stats()
        async with self._inflight_lock:
            inflight_request_count = len(self._inflight)
            inflight_keys = sorted(self._inflight.keys())[:20]
            oldest_inflight_started_at = min(self._inflight_started_at.values(), default=None)
        return {
            "providers": [
                {
                    "provider_id": activity.provider_id,
                    "active_requests": activity.active_requests,
                    "total_requests": activity.total_requests,
                    "coalesced_requests": activity.coalesced_requests,
                    "cooldown_skips": activity.cooldown_skips,
                    "cache_hits": activity.cache_hits,
                    "cache_misses": activity.cache_misses,
                    "stale_fallbacks": activity.stale_fallbacks,
                    "fallback_responses": activity.fallback_responses,
                    "errors": activity.errors,
                    "last_status": activity.last_status,
                    "last_error": activity.last_error,
                    "last_started_at": activity.last_started_at,
                    "last_finished_at": activity.last_finished_at,
                    "consecutive_failures": activity.consecutive_failures,
                    "cooldown_until": activity.cooldown_until,
                }
                for activity in sorted(self._activity.values(), key=lambda item: item.provider_id)
            ],
            "cache": {
                "entry_count": cache_stats.entry_count,
                "max_entries": cache_stats.max_entries,
                "expired_entry_count": cache_stats.expired_entry_count,
                "namespace_counts": cache_stats.namespace_counts,
                "stale_retention_seconds": cache_stats.stale_retention_seconds,
            },
            "coordination": {
                "inflight_request_count": inflight_request_count,
                "max_inflight_requests": self.max_inflight_requests,
                "inflight_keys": inflight_keys,
                "oldest_inflight_started_at": oldest_inflight_started_at,
                "coalesced_request_count": sum(activity.coalesced_requests for activity in self._activity.values()),
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
