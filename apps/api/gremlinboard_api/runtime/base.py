from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from gremlinboard_api.schemas.contracts import WidgetManifest


@dataclass(slots=True)
class RefreshDirective:
    mode: str
    interval_seconds: int
    reason: str | None = None


@dataclass(slots=True)
class ServiceContext:
    provider_registry: Any | None = None


class BaseWidgetService(ABC):
    def __init__(
        self,
        *,
        instance_id: str,
        manifest: WidgetManifest,
        config: dict[str, Any],
        service_context: ServiceContext | None = None,
    ):
        self.instance_id = instance_id
        self.manifest = manifest
        self.config = config
        self.service_context = service_context
        self.started_at: datetime | None = None
        self.state: dict[str, Any] = {}
        self._refresh_directive: RefreshDirective | None = None
        self._force_refresh_requested = False

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

    async def refresh(self, *, force: bool = False) -> dict[str, Any]:
        self._force_refresh_requested = force
        try:
            return await self.get_state()
        finally:
            self._force_refresh_requested = False

    async def invalidate_cache(self) -> None:
        provider_registry = getattr(self.service_context, "provider_registry", None)
        if provider_registry is not None:
            await provider_registry.runtime.invalidate_namespace(self.instance_id)

    def mark_started(self) -> None:
        self.started_at = datetime.now(timezone.utc)

    @property
    def force_refresh_requested(self) -> bool:
        return self._force_refresh_requested

    def get_refresh_directive(self) -> RefreshDirective | None:
        return self._refresh_directive

    def set_refresh_directive(self, directive: RefreshDirective | None) -> None:
        self._refresh_directive = directive

    def resolve_refresh_directive(
        self,
        *,
        live: bool,
        default_interval_seconds: int,
        live_interval_seconds: int,
    ) -> RefreshDirective:
        behavior = str(self.config.get("refresh_behavior") or "auto")
        interval_override = self._coerce_positive_int(self.config.get("refresh_interval_seconds"))
        if behavior == "manual":
            return RefreshDirective(
                mode="manual",
                interval_seconds=interval_override or default_interval_seconds,
                reason="manual override",
            )
        if behavior == "interval":
            return RefreshDirective(
                mode="interval",
                interval_seconds=interval_override or default_interval_seconds,
                reason="interval override",
            )
        if behavior == "live":
            return RefreshDirective(
                mode="live",
                interval_seconds=interval_override or live_interval_seconds,
                reason="live override",
            )
        return RefreshDirective(
            mode="live" if live else "interval",
            interval_seconds=interval_override or (live_interval_seconds if live else default_interval_seconds),
            reason="adaptive live mode" if live else "adaptive interval mode",
        )

    @staticmethod
    def _coerce_positive_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int) and value > 0:
            return value
        return None
