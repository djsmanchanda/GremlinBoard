from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class ProviderRequest:
    cache_namespace: str
    query: dict[str, Any]
    force_refresh: bool = False
    cache_ttl_seconds: int | None = None


@dataclass(slots=True)
class ProviderHealthSnapshot:
    provider_id: str
    label: str
    status: str = "idle"
    error: str | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    latency_ms: int | None = None
    consecutive_failures: int = 0
    cache_status: str = "none"
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "label": self.label,
            "status": self.status,
            "error": self.error,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "last_error_at": self.last_error_at.isoformat() if self.last_error_at else None,
            "latency_ms": self.latency_ms,
            "consecutive_failures": self.consecutive_failures,
            "cache_status": self.cache_status,
            "fallback_used": self.fallback_used,
        }


@dataclass(slots=True)
class ProviderResult:
    provider_id: str
    label: str
    data: Any
    health: ProviderHealthSnapshot
    fetched_at: datetime
    source_url: str | None = None
    cached: bool = False
    stale: bool = False
    fallback: bool = False

    def to_meta(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "label": self.label,
            "fetched_at": self.fetched_at.isoformat(),
            "source_url": self.source_url,
            "cached": self.cached,
            "stale": self.stale,
            "fallback": self.fallback,
            "health": self.health.to_dict(),
        }
