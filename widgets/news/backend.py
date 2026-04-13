from __future__ import annotations

from gremlinboard_api.providers.models import ProviderRequest
from gremlinboard_api.runtime.base import BaseWidgetService
from gremlinboard_api.services.fixtures import build_news_items


class NewsWidgetService(BaseWidgetService):
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
        topic = str(self.config.get("topic", "openclaw"))
        provider_id = self._resolve_provider()
        provider_registry = getattr(self.service_context, "provider_registry", None)
        if provider_registry is None:
            headlines = build_news_items(topic)
            result_meta = {
                "cached": False,
                "stale": False,
                "fallback": True,
                "source_url": None,
                "health": {
                    "provider_id": "unavailable",
                    "label": "Unavailable",
                    "status": "degraded",
                    "error": "provider registry is not available",
                    "last_success_at": None,
                    "last_error_at": None,
                    "latency_ms": None,
                    "consecutive_failures": 0,
                    "cache_status": "fallback",
                    "fallback_used": True,
                },
            }
        else:
            provider = provider_registry.create_news_provider(provider_id)
            result = await provider.fetch(
                request=ProviderRequest(
                    cache_namespace=self.instance_id,
                    query={
                        "topic": topic,
                        "feed_urls": self.config.get("feed_urls", []),
                        "limit": self.config.get("limit", 5),
                        "language": self.config.get("language", "en"),
                    },
                    force_refresh=self.force_refresh_requested,
                    cache_ttl_seconds=self._cache_ttl_seconds(default=300),
                )
            )
            payload = result.data if isinstance(result.data, dict) else {"headlines": build_news_items(topic)}
            headlines = payload.get("headlines", build_news_items(topic))
            result_meta = result.to_meta()

        directive = self.resolve_refresh_directive(
            live=False,
            default_interval_seconds=600,
            live_interval_seconds=180,
        )
        self.set_refresh_directive(directive)
        state = {
            "kind": "news",
            "topic": topic,
            "provider": provider_id,
            "headlines": headlines,
            "meta": {
                "providers": [result_meta["health"]],
                "primary_provider": provider_id,
                "cached": result_meta.get("cached", False),
                "stale": result_meta.get("stale", False),
                "fallback": result_meta.get("fallback", False),
                "source_url": result_meta.get("source_url"),
                "refresh": {
                    "mode": directive.mode,
                    "interval_seconds": directive.interval_seconds,
                    "reason": directive.reason,
                },
            },
        }
        self.state = state
        return state

    def _resolve_provider(self) -> str:
        configured = str(self.config.get("provider") or "rss")
        if configured != "auto":
            return configured
        provider_registry = getattr(self.service_context, "provider_registry", None)
        if provider_registry is None:
            return "rss"
        newsapi_key = provider_registry.runtime.secrets.resolve("newsapi").get("api_key")
        return "newsapi" if newsapi_key else "rss"

    def _cache_ttl_seconds(self, *, default: int) -> int:
        value = self.config.get("cache_ttl_seconds")
        if isinstance(value, int) and value > 0 and not isinstance(value, bool):
            return value
        return default
