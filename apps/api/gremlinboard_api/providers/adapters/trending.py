from __future__ import annotations

import asyncio
from typing import Any

from gremlinboard_api.config import settings
from gremlinboard_api.providers.base import ExternalDataProvider
from gremlinboard_api.services.fixtures import build_trending_sections


class RedditProvider(ExternalDataProvider):
    provider_id = "reddit"
    label = "Reddit"
    default_ttl_seconds = 90

    async def fetch_remote(self, *, query: dict[str, Any]) -> dict[str, Any]:
        subreddit = str(query.get("subreddit") or "technology")
        listing = str(query.get("listing") or "hot")
        limit = max(int(query.get("limit") or 5), 1)
        response = await self.request_json(
            f"https://www.reddit.com/r/{subreddit}/{listing}.json",
            params={"limit": limit},
            headers={"User-Agent": settings.reddit_user_agent},
        )
        items = response.get("data", {}).get("children", [])
        if not items:
            raise ValueError("reddit returned no items")
        return {
            "data": {
                "source": "reddit",
                "items": [
                    {
                        "label": str(item.get("data", {}).get("title") or "Untitled"),
                        "score": int(item.get("data", {}).get("score") or 0),
                        "href": f"https://reddit.com{item.get('data', {}).get('permalink', '')}",
                    }
                    for item in items[:limit]
                ],
            },
            "source_url": f"https://www.reddit.com/r/{subreddit}/{listing}.json",
        }

    def fallback_response(self, *, query: dict[str, Any], error: Exception | None) -> Any | None:
        return build_trending_sections(["reddit"])[0]


class HackerNewsProvider(ExternalDataProvider):
    provider_id = "hackernews"
    label = "Hacker News"
    default_ttl_seconds = 120

    async def fetch_remote(self, *, query: dict[str, Any]) -> dict[str, Any]:
        story_type = str(query.get("story_type") or "top")
        limit = max(int(query.get("limit") or 5), 1)
        ids = await self.request_json(f"https://hacker-news.firebaseio.com/v0/{story_type}stories.json")
        if not isinstance(ids, list) or not ids:
            raise ValueError("hackernews returned no story ids")

        async def load_item(story_id: int) -> dict[str, Any]:
            return await self.request_json(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")

        raw_items = await asyncio.gather(*(load_item(int(story_id)) for story_id in ids[:limit]))
        items = [
            {
                "label": str(item.get("title") or "Untitled"),
                "score": int(item.get("score") or 0),
                "href": str(item.get("url") or f"https://news.ycombinator.com/item?id={item.get('id')}"),
            }
            for item in raw_items
            if isinstance(item, dict)
        ]
        if not items:
            raise ValueError("hackernews returned no stories")
        return {
            "data": {"source": "hackernews", "items": items},
            "source_url": "https://hacker-news.firebaseio.com",
        }

    def fallback_response(self, *, query: dict[str, Any], error: Exception | None) -> Any | None:
        return build_trending_sections(["hackernews"])[0]


class XSearchProvider(ExternalDataProvider):
    provider_id = "x"
    label = "X"
    default_ttl_seconds = 120

    async def fetch_remote(self, *, query: dict[str, Any]) -> dict[str, Any]:
        bearer_token = self.require_credential("bearer_token")
        limit = max(min(int(query.get("limit") or 5), 10), 1)
        search_query = str(query.get("search_query") or "technology OR ai")
        response = await self.request_json(
            f"{settings.x_api_base_url}/2/tweets/search/recent",
            params={
                "query": search_query,
                "max_results": limit,
                "tweet.fields": "public_metrics,created_at",
            },
            headers={"Authorization": f"Bearer {bearer_token}"},
        )
        tweets = response.get("data") or []
        if not tweets:
            raise ValueError("x returned no posts")
        return {
            "data": {
                "source": "x",
                "items": [
                    {
                        "label": str(tweet.get("text") or "Untitled").replace("\n", " ")[:120],
                        "score": int((tweet.get("public_metrics") or {}).get("like_count") or 0),
                        "href": "https://x.com/i/status/" + str(tweet.get("id")),
                    }
                    for tweet in tweets[:limit]
                ],
            },
            "source_url": settings.x_api_base_url,
        }

    def fallback_response(self, *, query: dict[str, Any], error: Exception | None) -> Any | None:
        return build_trending_sections(["x"])[0]
