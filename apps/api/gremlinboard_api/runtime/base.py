from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from gremlinboard_api.schemas.contracts import WidgetManifest


class BaseWidgetService(ABC):
    def __init__(self, *, instance_id: str, manifest: WidgetManifest, config: dict[str, Any]):
        self.instance_id = instance_id
        self.manifest = manifest
        self.config = config
        self.started_at: datetime | None = None
        self.state: dict[str, Any] = {}

    async def set_config(self, config: dict[str, Any]) -> None:
        self.config = config

    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def get_state(self) -> dict[str, Any]:
        raise NotImplementedError

    async def refresh(self) -> dict[str, Any]:
        return await self.get_state()

    def mark_started(self) -> None:
        self.started_at = datetime.now(timezone.utc)
