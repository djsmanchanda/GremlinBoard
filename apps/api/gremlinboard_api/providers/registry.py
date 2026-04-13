from __future__ import annotations

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


class ProviderRuntime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache = ResponseCache()
        self.secrets = SecretResolver(settings)
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
