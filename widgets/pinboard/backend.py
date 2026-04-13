from __future__ import annotations

from gremlinboard_api.runtime.base import BaseWidgetService


class PinboardWidgetService(BaseWidgetService):
    async def start(self) -> None:
        self.state = await self.get_state()

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        return {"status": "running", "expired": False}

    async def get_state(self) -> dict[str, object]:
        return {
            "kind": "pinboard",
            "notes": self.config.get("notes", []),
        }
