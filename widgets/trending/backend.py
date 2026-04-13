from __future__ import annotations

from gremlinboard_api.runtime.base import BaseWidgetService
from gremlinboard_api.services.fixtures import build_trending_sections


class TrendingWidgetService(BaseWidgetService):
    async def start(self) -> None:
        self.state = await self.get_state()

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        return {"status": "running", "expired": False}

    async def get_state(self) -> dict[str, object]:
        sources = self.config.get("sources", ["reddit", "x", "hackernews"])
        return {
            "kind": "trending",
            "sections": build_trending_sections(sources),
        }
