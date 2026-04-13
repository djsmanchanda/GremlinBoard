from __future__ import annotations

from typing import Any
from xml.etree import ElementTree

from gremlinboard_api.config import settings
from gremlinboard_api.providers.base import ExternalDataProvider
from gremlinboard_api.services.fixtures import build_news_items


def _item_text(node, path: str) -> str | None:
    child = node.find(path)
    if child is None or child.text is None:
        return None
    return child.text.strip()


class RssNewsProvider(ExternalDataProvider):
    provider_id = "rss"
    label = "RSS"
    default_ttl_seconds = 300

    async def fetch_remote(self, *, query: dict[str, Any]) -> dict[str, Any]:
        feed_urls = query.get("feed_urls") or []
        topic = str(query.get("topic") or "general")
        limit = max(int(query.get("limit") or 5), 1)
        headlines: list[dict[str, str]] = []
        for feed_url in [str(url) for url in feed_urls if url]:
            document = await self.request_text(feed_url)
            root = ElementTree.fromstring(document)
            channel = root.find("channel")
            items = channel.findall("item") if channel is not None else root.findall("{http://www.w3.org/2005/Atom}entry")
            source = _item_text(channel, "title") if channel is not None else "RSS Feed"
            for item in items:
                title = _item_text(item, "title") or _item_text(item, "{http://www.w3.org/2005/Atom}title")
                summary = _item_text(item, "description") or _item_text(
                    item,
                    "{http://www.w3.org/2005/Atom}summary",
                )
                if title is None:
                    continue
                haystack = " ".join(filter(None, [title, summary or ""]))
                if topic.lower() != "general" and topic.lower() not in haystack.lower():
                    continue
                headlines.append(
                    {
                        "title": title,
                        "summary": summary or "Live feed item",
                        "source": source,
                        "published_at": _item_text(item, "pubDate")
                        or _item_text(item, "{http://www.w3.org/2005/Atom}updated")
                        or "recent",
                    }
                )
                if len(headlines) >= limit:
                    break
            if len(headlines) >= limit:
                break

        if not headlines:
            raise ValueError("rss provider returned no headlines")
        return {
            "data": {"headlines": headlines},
            "source_url": str(feed_urls[0]) if feed_urls else None,
        }

    def fallback_response(self, *, query: dict[str, Any], error: Exception | None) -> Any | None:
        return {"headlines": build_news_items(str(query.get("topic") or "general"))}


class NewsApiProvider(ExternalDataProvider):
    provider_id = "newsapi"
    label = "NewsAPI"
    default_ttl_seconds = 180

    async def fetch_remote(self, *, query: dict[str, Any]) -> dict[str, Any]:
        api_key = self.require_credential("api_key")
        topic = str(query.get("topic") or "technology")
        limit = max(int(query.get("limit") or 5), 1)
        response = await self.request_json(
            f"{settings.news_api_base_url}/v2/everything",
            params={
                "q": topic,
                "language": str(query.get("language") or "en"),
                "pageSize": limit,
                "sortBy": "publishedAt",
            },
            headers={"X-Api-Key": api_key},
        )
        articles = response.get("articles") or []
        if not articles:
            raise ValueError("newsapi returned no articles")
        headlines = [
            {
                "title": str(article.get("title") or "Untitled"),
                "summary": str(article.get("description") or "No summary available"),
                "source": str((article.get("source") or {}).get("name") or "NewsAPI"),
                "published_at": str(article.get("publishedAt") or "recent"),
            }
            for article in articles[:limit]
        ]
        return {
            "data": {"headlines": headlines},
            "source_url": settings.news_api_base_url,
        }

    def fallback_response(self, *, query: dict[str, Any], error: Exception | None) -> Any | None:
        return {"headlines": build_news_items(str(query.get("topic") or "general"))}
