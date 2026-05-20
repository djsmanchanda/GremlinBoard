from __future__ import annotations

from gremlinboard_api.runtime.base import BaseWidgetService, RefreshDirective


class AgentOverviewWidgetService(BaseWidgetService):
    async def start(self) -> None:
        self.state = await self.get_state()

    async def stop(self) -> None:
        return None

    async def health(self) -> dict[str, object]:
        return {"status": "running", "expired": False}

    async def get_state(self) -> dict[str, object]:
        interval_seconds = int(self.config.get("refresh_interval_seconds") or 30)
        self.set_refresh_directive(
            RefreshDirective(
                mode="manual" if self.config.get("refresh_behavior") == "manual" else "interval",
                interval_seconds=interval_seconds,
                reason="agent overview runtime view",
            )
        )
        return {
            "kind": "agent_overview",
            "summary": {
                "active": 0,
                "queued": 0,
                "needs_review": 0,
                "failed": 0,
                "completed": 0,
            },
            "agents": [],
            "timeline": [],
            "meta": {
                "source": "runtime_api",
                "refresh": {
                    "mode": "event_stream",
                    "interval_seconds": interval_seconds,
                    "reason": "agent overview reconciles from agent APIs and runtime events",
                },
            },
        }
