from __future__ import annotations

from gremlinboard_api.providers.models import ProviderRequest
from gremlinboard_api.runtime.base import BaseWidgetService
from gremlinboard_api.services.fixtures import build_sports_state


class SportsWidgetService(BaseWidgetService):
    async def start(self) -> None:
        self.state = await self.get_state()

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        meta = self.state.get("meta", {}) if isinstance(self.state, dict) else {}
        providers = meta.get("providers") if isinstance(meta.get("providers"), list) else []
        degraded = any(isinstance(item, dict) and item.get("status") == "degraded" for item in providers)
        return {
            "status": "degraded" if degraded else "running",
            "expired": False,
            "providers": providers,
        }

    async def get_state(self) -> dict[str, object]:
        sport = self.config.get("sport", "ipl")
        normalized_sport = sport if sport in {"ipl", "f1", "football"} else "football"
        provider_id = self._resolve_provider(normalized_sport)
        provider_registry = getattr(self.service_context, "provider_registry", None)
        if provider_registry is None:
            payload = build_sports_state(normalized_sport) | {"live": normalized_sport != "f1"}
            result_meta = {
                "provider_id": "unavailable",
                "label": "Unavailable",
                "cached": False,
                "stale": False,
                "fallback": True,
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
            provider = provider_registry.create_sports_provider(provider_id)
            result = await provider.fetch(
                request=ProviderRequest(
                    cache_namespace=self.instance_id,
                    query={
                        "sport": normalized_sport,
                        "competition_code": self.config.get("competition_code", "PL"),
                        "tournament": self.config.get("tournament", "IPL"),
                        "year": self.config.get("year"),
                    },
                    force_refresh=self.force_refresh_requested,
                    cache_ttl_seconds=self._cache_ttl_seconds(default=20),
                )
            )
            payload = result.data if isinstance(result.data, dict) else build_sports_state(normalized_sport)
            result_meta = result.to_meta()

        directive = self.resolve_refresh_directive(
            live=bool(payload.get("live")),
            default_interval_seconds=180,
            live_interval_seconds=60,
        )
        self.set_refresh_directive(directive)
        state = {
            "kind": "sports",
            "sport": normalized_sport,
            "provider": provider_id,
            "headline": payload.get("headline", "Sports Pulse"),
            "status": payload.get("status", "Live"),
            "entries": payload.get("entries", []),
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

    def _resolve_provider(self, sport: str) -> str:
        configured = str(self.config.get("provider") or "auto")
        if configured != "auto":
            return configured
        return {
            "ipl": "cricketdata",
            "f1": "openf1",
            "football": "football-data",
        }.get(sport, "football-data")

    def _cache_ttl_seconds(self, *, default: int) -> int:
        value = self.config.get("cache_ttl_seconds")
        if isinstance(value, int) and value > 0 and not isinstance(value, bool):
            return value
        return default
