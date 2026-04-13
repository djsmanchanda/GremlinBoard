from __future__ import annotations

from gremlinboard_api.runtime.base import BaseWidgetService
from gremlinboard_api.services.fixtures import build_sports_state


class SportsWidgetService(BaseWidgetService):
    async def start(self) -> None:
        self.state = await self.get_state()

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        return {"status": "running", "expired": False}

    async def get_state(self) -> dict[str, object]:
        sport = self.config.get("sport", "ipl")
        payload = build_sports_state(sport if sport in {"ipl", "f1", "football"} else "football")
        payload["sport"] = sport
        return payload
