from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(slots=True)
class CacheEntry:
    value: Any
    created_at: datetime
    expires_at: datetime
    discard_at: datetime

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= datetime.now(timezone.utc)

    @property
    def is_discarded(self) -> bool:
        return self.discard_at <= datetime.now(timezone.utc)


@dataclass(slots=True)
class CacheStats:
    entry_count: int
    max_entries: int
    expired_entry_count: int
    namespace_counts: dict[str, int]
    stale_retention_seconds: int


class ResponseCache:
    def __init__(self, *, max_entries: int = 256, stale_retention_seconds: int = 600) -> None:
        self._entries: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self.max_entries = max(max_entries, 1)
        self.stale_retention_seconds = max(stale_retention_seconds, 0)

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            self._prune_discarded(datetime.now(timezone.utc))
            entry = self._entries.get(key)
            if entry is None or entry.is_expired:
                return None
            return entry.value

    async def peek(self, key: str) -> Any | None:
        async with self._lock:
            self._prune_discarded(datetime.now(timezone.utc))
            entry = self._entries.get(key)
            return None if entry is None else entry.value

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        now = datetime.now(timezone.utc)
        async with self._lock:
            self._prune_discarded(now)
            if len(self._entries) >= self.max_entries and key not in self._entries:
                oldest_key = min(self._entries, key=lambda entry_key: self._entries[entry_key].created_at)
                self._entries.pop(oldest_key, None)
            expires_at = now + timedelta(seconds=max(int(ttl_seconds), 1))
            self._entries[key] = CacheEntry(
                value=value,
                created_at=now,
                expires_at=expires_at,
                discard_at=expires_at + timedelta(seconds=self.stale_retention_seconds),
            )

    async def invalidate_prefix(self, prefix: str) -> None:
        async with self._lock:
            for key in [entry_key for entry_key in self._entries if entry_key.startswith(prefix)]:
                self._entries.pop(key, None)

    async def stats(self) -> CacheStats:
        now = datetime.now(timezone.utc)
        async with self._lock:
            self._prune_discarded(now)
            namespace_counts: dict[str, int] = {}
            expired_entry_count = 0
            for key, entry in self._entries.items():
                namespace = key.split(":", 1)[0] if ":" in key else "default"
                namespace_counts[namespace] = namespace_counts.get(namespace, 0) + 1
                if entry.expires_at <= now:
                    expired_entry_count += 1
            return CacheStats(
                entry_count=len(self._entries),
                max_entries=self.max_entries,
                expired_entry_count=expired_entry_count,
                namespace_counts=namespace_counts,
                stale_retention_seconds=self.stale_retention_seconds,
            )

    def _prune_discarded(self, now: datetime) -> None:
        for key in [entry_key for entry_key, entry in self._entries.items() if entry.discard_at <= now]:
            self._entries.pop(key, None)
