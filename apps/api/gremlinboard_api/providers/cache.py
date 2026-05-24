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

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= datetime.now(timezone.utc)


class ResponseCache:
    def __init__(self, *, max_entries: int = 256) -> None:
        self._entries: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self.max_entries = max(max_entries, 1)

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.is_expired:
                return None
            return entry.value

    async def peek(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._entries.get(key)
            return None if entry is None else entry.value

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        now = datetime.now(timezone.utc)
        async with self._lock:
            self._prune_expired(now)
            if len(self._entries) >= self.max_entries and key not in self._entries:
                oldest_key = min(self._entries, key=lambda entry_key: self._entries[entry_key].created_at)
                self._entries.pop(oldest_key, None)
            self._entries[key] = CacheEntry(
                value=value,
                created_at=now,
                expires_at=now + timedelta(seconds=max(int(ttl_seconds), 1)),
            )

    async def invalidate_prefix(self, prefix: str) -> None:
        async with self._lock:
            for key in [entry_key for entry_key in self._entries if entry_key.startswith(prefix)]:
                self._entries.pop(key, None)

    def _prune_expired(self, now: datetime) -> None:
        for key in [entry_key for entry_key, entry in self._entries.items() if entry.expires_at <= now]:
            self._entries.pop(key, None)
