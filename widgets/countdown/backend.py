from __future__ import annotations

from datetime import datetime, timezone

from gremlinboard_api.runtime.base import BaseWidgetService


class CountdownWidgetService(BaseWidgetService):
    async def start(self) -> None:
        self.state = await self.get_state()

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        target = datetime.fromisoformat(self.config["target_time"])
        expired = datetime.now(timezone.utc) >= target
        return {
            "status": "expired" if expired else "running",
            "expired": expired,
            "expires_at": target.isoformat(),
        }

    async def get_state(self) -> dict[str, object]:
        target = datetime.fromisoformat(self.config["target_time"])
        remaining = max(int((target - datetime.now(timezone.utc)).total_seconds()), 0)
        hours, remainder = divmod(remaining, 3600)
        minutes, seconds = divmod(remainder, 60)
        return {
            "kind": "countdown",
            "label": self.config.get("label", "Countdown"),
            "target_time": target.isoformat(),
            "remaining_seconds": remaining,
            "formatted_remaining": f"{hours:02d}:{minutes:02d}:{seconds:02d}",
            "complete": remaining == 0,
        }
