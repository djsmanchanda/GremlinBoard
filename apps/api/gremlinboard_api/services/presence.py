from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from gremlinboard_api.schemas.contracts import (
    PresenceSnapshotRead,
    PresenceSource,
    PresenceSourceRead,
    RuntimeEventCategory,
    RuntimeEventPersistence,
    RuntimeEventSource,
    RuntimeEventVisibility,
    RuntimePowerState,
)

if TYPE_CHECKING:
    from gremlinboard_api.runtime.events import EventBus


class PresenceManager:
    def __init__(
        self,
        *,
        event_bus: "EventBus",
        board_id: str,
        idle_after_seconds: int = 90,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.board_id = board_id
        self.idle_after_seconds = max(idle_after_seconds, 1)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._last_seen: dict[PresenceSource, datetime] = {}
        self._active_counts: Counter[PresenceSource] = Counter()
        self._suspended = False
        self._suspend_reason: str | None = None
        self._last_state: RuntimePowerState | None = None
        self._lock = asyncio.Lock()

    async def record_activity(
        self,
        source: PresenceSource | str,
        *,
        detail: str | None = None,
        publish: bool = False,
    ) -> PresenceSnapshotRead:
        source_value = self._coerce_source(source)
        async with self._lock:
            self._last_seen[source_value] = self._now()
            snapshot = self._build_snapshot_locked(degraded=False)
        if publish:
            await self.event_bus.publish_event(
                "operator.activity",
                category=RuntimeEventCategory.OPERATOR,
                source=RuntimeEventSource(component="presence_manager", board_id=self.board_id),
                payload={"source": source_value.value, "detail": detail},
                visibility=RuntimeEventVisibility.INTERNAL,
                persistence=RuntimeEventPersistence.EPHEMERAL,
                replayable=False,
            )
        await self._publish_transition_if_needed(snapshot)
        return snapshot

    async def websocket_connected(self) -> str:
        token = uuid4().hex
        async with self._lock:
            self._active_counts[PresenceSource.WEBSOCKET] += 1
            self._last_seen[PresenceSource.WEBSOCKET] = self._now()
            snapshot = self._build_snapshot_locked(degraded=False)
        await self._publish_transition_if_needed(snapshot)
        return token

    async def websocket_disconnected(self, token: str | None = None) -> PresenceSnapshotRead:
        del token
        async with self._lock:
            if self._active_counts[PresenceSource.WEBSOCKET] > 0:
                self._active_counts[PresenceSource.WEBSOCKET] -= 1
            if self._active_counts[PresenceSource.WEBSOCKET] <= 0:
                self._active_counts.pop(PresenceSource.WEBSOCKET, None)
            self._last_seen[PresenceSource.WEBSOCKET] = self._now()
            snapshot = self._build_snapshot_locked(degraded=False)
        await self._publish_transition_if_needed(snapshot)
        return snapshot

    async def suspend(self, *, reason: str | None = None) -> PresenceSnapshotRead:
        async with self._lock:
            self._suspended = True
            self._suspend_reason = reason or "manual suspend"
            snapshot = self._build_snapshot_locked(degraded=False)
        await self._publish_transition_if_needed(snapshot)
        return snapshot

    async def resume(self, *, source: PresenceSource | str = PresenceSource.OPERATOR) -> PresenceSnapshotRead:
        async with self._lock:
            self._suspended = False
            self._suspend_reason = None
            self._last_seen[self._coerce_source(source)] = self._now()
            snapshot = self._build_snapshot_locked(degraded=False)
        await self._publish_transition_if_needed(snapshot)
        return snapshot

    async def snapshot(self, *, degraded: bool = False, reason: str | None = None) -> PresenceSnapshotRead:
        async with self._lock:
            snapshot = self._build_snapshot_locked(degraded=degraded, reason=reason)
        await self._publish_transition_if_needed(snapshot)
        return snapshot

    async def should_pause_scheduled_work(self) -> bool:
        snapshot = await self.snapshot()
        return snapshot.state in {RuntimePowerState.IDLE, RuntimePowerState.SUSPENDED}

    def _build_snapshot_locked(
        self,
        *,
        degraded: bool,
        reason: str | None = None,
    ) -> PresenceSnapshotRead:
        now = self._now()
        recent_interaction_at = max(self._last_seen.values()) if self._last_seen else None
        active_websocket_count = self._active_counts[PresenceSource.WEBSOCKET]
        recently_active = (
            recent_interaction_at is not None
            and (now - recent_interaction_at).total_seconds() <= self.idle_after_seconds
        )

        if self._suspended:
            state = RuntimePowerState.SUSPENDED
            state_reason = self._suspend_reason
        elif degraded:
            state = RuntimePowerState.DEGRADED
            state_reason = reason or "runtime degradation detected"
        elif active_websocket_count > 0 or recently_active:
            state = RuntimePowerState.ACTIVE
            state_reason = reason
        else:
            state = RuntimePowerState.IDLE
            state_reason = reason or "no recent operator presence"

        active_sources = [
            PresenceSourceRead(
                source=source,
                active=self._active_counts[source],
                last_seen_at=self._last_seen.get(source),
            )
            for source in sorted(PresenceSource, key=lambda item: item.value)
            if self._active_counts[source] > 0 or source in self._last_seen
        ]

        return PresenceSnapshotRead(
            state=state,
            active_sources=active_sources,
            active_websocket_count=active_websocket_count,
            recent_interaction_at=recent_interaction_at,
            idle_after_seconds=self.idle_after_seconds,
            suspended=self._suspended,
            degraded=degraded,
            reason=state_reason,
            updated_at=now,
        )

    async def _publish_transition_if_needed(self, snapshot: PresenceSnapshotRead) -> None:
        if snapshot.state == self._last_state:
            return
        previous = self._last_state
        self._last_state = snapshot.state
        await self.event_bus.publish_event(
            f"runtime.{snapshot.state.value}_entered",
            category=RuntimeEventCategory.RUNTIME,
            source=RuntimeEventSource(component="presence_manager", board_id=self.board_id),
            payload={
                "previous_state": previous.value if previous is not None else None,
                "state": snapshot.state.value,
                "reason": snapshot.reason,
                "active_websocket_count": snapshot.active_websocket_count,
                "recent_interaction_at": (
                    snapshot.recent_interaction_at.isoformat() if snapshot.recent_interaction_at else None
                ),
            },
            visibility=RuntimeEventVisibility.BOTH,
            persistence=RuntimeEventPersistence.TIMELINE,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _coerce_source(source: PresenceSource | str) -> PresenceSource:
        return source if isinstance(source, PresenceSource) else PresenceSource(source)
