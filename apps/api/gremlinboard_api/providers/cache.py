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
    def __init__(self) -> None:
        self._entries: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

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
            self._entries[key] = CacheEntry(
                value=value,
                created_at=now,
                expires_at=now + timedelta(seconds=max(int(ttl_seconds), 1)),
            )

    async def invalidate_prefix(self, prefix: str) -> None:
        async with self._lock:
            for key in [entry_key for entry_key in self._entries if entry_key.startswith(prefix)]:
                self._entries.pop(key, None)
