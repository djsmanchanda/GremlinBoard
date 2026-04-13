from __future__ import annotations

import asyncio

from gremlinboard_api.providers.models import ProviderRequest
from gremlinboard_api.runtime.base import BaseWidgetService
from gremlinboard_api.services.fixtures import build_trending_sections


class TrendingWidgetService(BaseWidgetService):
    async def start(self) -> None:
        self.state = await self.get_state()

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        meta = self.state.get("meta", {}) if isinstance(self.state, dict) else {}
        providers = meta.get("providers") if isinstance(meta.get("providers"), list) else []
        degraded = any(isinstance(item, dict) and item.get("status") == "degraded" for item in providers)
        return {"status": "degraded" if degraded else "running", "expired": False, "providers": providers}

    async def get_state(self) -> dict[str, object]:
        sources = self.config.get("sources", ["reddit", "x", "hackernews"])
        normalized_sources = [str(source) for source in sources if str(source) in {"reddit", "x", "hackernews"}]
        provider_registry = getattr(self.service_context, "provider_registry", None)
        if provider_registry is None:
            sections = build_trending_sections(normalized_sources)
            provider_states = [
                {
                    "provider_id": source,
                    "label": source.title(),
                    "status": "degraded",
                    "error": "provider registry is not available",
                    "last_success_at": None,
                    "last_error_at": None,
                    "latency_ms": None,
                    "consecutive_failures": 0,
                    "cache_status": "fallback",
                    "fallback_used": True,
                }
                for source in normalized_sources
            ]
            cached = False
            stale = False
            fallback = True
            source_url = None
        else:
            async def fetch_source(source: str):
                provider = provider_registry.create_trending_provider(source)
                return await provider.fetch(
                    request=ProviderRequest(
                        cache_namespace=self.instance_id,
                        query={
                            "subreddit": self.config.get("subreddit", "technology"),
                            "listing": self.config.get("reddit_listing", "hot"),
                            "search_query": self.config.get("x_query", "technology OR ai"),
                            "story_type": self.config.get("hn_story_type", "top"),
                            "limit": self.config.get("limit", 5),
                        },
                        force_refresh=self.force_refresh_requested,
                        cache_ttl_seconds=self._cache_ttl_seconds(default=120),
                    )
                )

            results = await asyncio.gather(*(fetch_source(source) for source in normalized_sources))
            sections = [
                result.data if isinstance(result.data, dict) else build_trending_sections([result.provider_id])[0]
                for result in results
            ]
            provider_states = [result.health.to_dict() for result in results]
            cached = any(result.cached for result in results)
            stale = any(result.stale for result in results)
            fallback = any(result.fallback for result in results)
            source_url = next((result.source_url for result in results if result.source_url), None)

        directive = self.resolve_refresh_directive(
            live="x" in normalized_sources,
            default_interval_seconds=300,
            live_interval_seconds=90,
        )
        self.set_refresh_directive(directive)
        state = {
            "kind": "trending",
            "sections": sections,
            "meta": {
                "providers": provider_states,
                "cached": cached,
                "stale": stale,
                "fallback": fallback,
                "source_url": source_url,
                "refresh": {
                    "mode": directive.mode,
                    "interval_seconds": directive.interval_seconds,
                    "reason": directive.reason,
                },
            },
        }
        self.state = state
        return state

    def _cache_ttl_seconds(self, *, default: int) -> int:
        value = self.config.get("cache_ttl_seconds")
        if isinstance(value, int) and value > 0 and not isinstance(value, bool):
            return value
        return default
