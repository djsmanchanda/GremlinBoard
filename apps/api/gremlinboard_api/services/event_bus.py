from __future__ import annotations

import asyncio
import uuid
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from gremlinboard_api.schemas.contracts import (
    RuntimeEventCategory,
    RuntimeEventEnvelope,
    RuntimeEventLevel,
    RuntimeEventPersistence,
    RuntimeEventSource,
    RuntimeEventVisibility,
)


SubscriberKind = Literal["internal", "websocket", "all"]


@dataclass(slots=True)
class EventSubscriber:
    id: str
    kind: SubscriberKind
    queue: asyncio.Queue[RuntimeEventEnvelope]
    categories: set[RuntimeEventCategory] | None = None
    event_types: set[str] | None = None
    dropped_events: int = 0
    stream_reset_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_enqueued_at: datetime | None = None
    last_overflow_at: datetime | None = None


@dataclass(slots=True)
class EventBusStats:
    subscriber_count: int = 0
    queued_event_count: int = 0
    dropped_event_count: int = 0
    published_event_count: int = 0
    replay_event_count: int = 0
    history_size: int = 0
    replay_oldest_sequence: int | None = None
    latest_sequence: int = 0
    stream_reset_count: int = 0
    websocket_queue_depth: int = 0
    internal_queue_depth: int = 0
    max_subscriber_queue_depth: int = 0
    websocket_dropped_event_count: int = 0
    replay_miss_count: int = 0
    replay_miss_reasons: dict[str, int] = field(default_factory=dict)
    snapshot_fallback_count: int = 0
    stale_subscriber_count: int = 0
    pruned_subscriber_count: int = 0


@dataclass(slots=True)
class EventSubscriberSnapshot:
    id: str
    kind: SubscriberKind
    queue_depth: int
    max_queue_size: int
    dropped_events: int
    stream_reset_count: int
    created_at: datetime
    last_enqueued_at: datetime | None = None
    last_overflow_at: datetime | None = None
    categories: list[str] = field(default_factory=list)
    event_types: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EventBusSnapshot:
    stats: EventBusStats
    subscribers: list[EventSubscriberSnapshot]
    recent_events: list[RuntimeEventEnvelope]
    observed_at: datetime


class TypedEventBus:
    def __init__(
        self,
        *,
        default_queue_size: int = 64,
        history_size: int = 128,
        boot_id: str | None = None,
    ) -> None:
        self.default_queue_size = default_queue_size
        self._history: deque[RuntimeEventEnvelope] = deque(maxlen=history_size)
        self._subscribers: dict[int, EventSubscriber] = {}
        self._next_subscriber_id = 1
        self._next_sequence = 1
        self._boot_id = boot_id if boot_id is not None else uuid.uuid4().hex
        self._published_event_count = 0
        self._replay_event_count = 0
        self._stream_reset_count = 0
        self._replay_miss_count = 0
        self._replay_miss_reasons: dict[str, int] = {}
        self._snapshot_fallback_count = 0
        self._pruned_subscriber_count = 0

    async def publish(
        self,
        event: RuntimeEventEnvelope | dict[str, Any],
        *,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> RuntimeEventEnvelope:
        envelope = self._coerce_event(
            event,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        envelope = envelope.model_copy(update={"sequence": self._next_sequence})
        self._next_sequence += 1
        self._published_event_count += 1
        if envelope.replayable:
            self._history.append(envelope)

        for subscriber in list(self._subscribers.values()):
            if not self._matches_subscriber(envelope, subscriber):
                continue
            if subscriber.queue.full():
                if subscriber.kind == "websocket":
                    dropped = self._drain_queue(subscriber.queue)
                    subscriber.dropped_events += dropped
                    subscriber.stream_reset_count += 1
                    subscriber.last_overflow_at = datetime.now(timezone.utc)
                    self._stream_reset_count += 1
                    subscriber.queue.put_nowait(
                        self._stream_reset_event(
                            sequence=envelope.sequence,
                            causation_id=envelope.id,
                            dropped_events=dropped,
                        )
                    )
                    subscriber.last_enqueued_at = datetime.now(timezone.utc)
                    continue
                try:
                    subscriber.queue.get_nowait()
                    self._safe_task_done(subscriber.queue)
                    subscriber.dropped_events += 1
                    subscriber.last_overflow_at = datetime.now(timezone.utc)
                except asyncio.QueueEmpty:
                    pass
            try:
                subscriber.queue.put_nowait(envelope)
                subscriber.last_enqueued_at = datetime.now(timezone.utc)
            except asyncio.QueueFull:
                subscriber.dropped_events += 1
                subscriber.last_overflow_at = datetime.now(timezone.utc)
        return envelope

    async def publish_event(
        self,
        event_type: str,
        *,
        category: RuntimeEventCategory | str | None = None,
        source: RuntimeEventSource | dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        level: RuntimeEventLevel | str = RuntimeEventLevel.INFO,
        message: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        visibility: RuntimeEventVisibility | str = RuntimeEventVisibility.BOTH,
        persistence: RuntimeEventPersistence | str = RuntimeEventPersistence.EPHEMERAL,
        replayable: bool = True,
    ) -> RuntimeEventEnvelope:
        return await self.publish(
            RuntimeEventEnvelope(
                type=event_type,
                category=self._coerce_category(category, event_type),
                level=RuntimeEventLevel(level),
                message=message,
                source=self._coerce_source(source),
                correlation_id=correlation_id,
                causation_id=causation_id,
                visibility=RuntimeEventVisibility(visibility),
                persistence=RuntimeEventPersistence(persistence),
                replayable=replayable,
                payload=payload or {},
            )
        )

    def subscribe(
        self,
        *,
        kind: SubscriberKind = "internal",
        max_queue_size: int | None = None,
        categories: Iterable[RuntimeEventCategory | str] | None = None,
        event_types: Iterable[str] | None = None,
        include_replay: bool = False,
    ) -> asyncio.Queue[RuntimeEventEnvelope]:
        queue: asyncio.Queue[RuntimeEventEnvelope] = asyncio.Queue(maxsize=max_queue_size or self.default_queue_size)
        subscriber = EventSubscriber(
            id=str(self._next_subscriber_id),
            kind=kind,
            queue=queue,
            categories={RuntimeEventCategory(category) for category in categories} if categories else None,
            event_types=set(event_types) if event_types else None,
        )
        self._next_subscriber_id += 1
        self._subscribers[id(queue)] = subscriber

        if include_replay:
            for event in self._history:
                if self._matches_subscriber(event, subscriber):
                    if queue.full():
                        try:
                            queue.get_nowait()
                            self._safe_task_done(queue)
                            subscriber.dropped_events += 1
                        except asyncio.QueueEmpty:
                            pass
                    try:
                        queue.put_nowait(event)
                        subscriber.last_enqueued_at = datetime.now(timezone.utc)
                        self._replay_event_count += 1
                    except asyncio.QueueFull:
                        subscriber.dropped_events += 1
                        subscriber.last_overflow_at = datetime.now(timezone.utc)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[RuntimeEventEnvelope]) -> None:
        self._subscribers.pop(id(queue), None)

    def replay(
        self,
        *,
        after_sequence: int = 0,
        categories: Iterable[RuntimeEventCategory | str] | None = None,
        event_types: Iterable[str] | None = None,
        kind: SubscriberKind = "all",
    ) -> list[RuntimeEventEnvelope]:
        category_filter = {RuntimeEventCategory(category) for category in categories} if categories else None
        event_type_filter = set(event_types) if event_types else None
        subscriber = EventSubscriber(
            id="replay",
            kind=kind,
            queue=asyncio.Queue(maxsize=1),
            categories=category_filter,
            event_types=event_type_filter,
        )
        return [
            event
            for event in self._history
            if event.sequence > after_sequence
            and self._matches_subscriber(event, subscriber)
        ]

    def recent_events(
        self,
        *,
        limit: int = 100,
        categories: Iterable[RuntimeEventCategory | str] | None = None,
        event_types: Iterable[str] | None = None,
        kind: SubscriberKind = "all",
    ) -> list[RuntimeEventEnvelope]:
        category_filter = {RuntimeEventCategory(category) for category in categories} if categories else None
        event_type_filter = set(event_types) if event_types else None
        subscriber = EventSubscriber(
            id="recent",
            kind=kind,
            queue=asyncio.Queue(maxsize=1),
            categories=category_filter,
            event_types=event_type_filter,
        )
        bounded_limit = min(max(limit, 1), self._history.maxlen or 128)
        matches = [
            event
            for event in self._history
            if self._matches_subscriber(event, subscriber)
        ]
        return matches[-bounded_limit:]

    def clear_replay_history(self) -> int:
        cleared = len(self._history)
        self._history.clear()
        return cleared

    def can_replay(self, after_sequence: int, boot_id: str | None = None) -> bool:
        if boot_id is not None and boot_id != self._boot_id:
            return False
        if after_sequence < 0:
            return False
        if after_sequence > self.latest_sequence:
            return False
        if not self._history:
            return after_sequence >= self.latest_sequence
        return after_sequence >= self._history[0].sequence - 1

    def record_replay_miss(self, reason: str = "unknown") -> None:
        self._replay_miss_count += 1
        self._replay_miss_reasons[reason] = self._replay_miss_reasons.get(reason, 0) + 1

    def record_snapshot_fallback(self) -> None:
        self._snapshot_fallback_count += 1

    def classify_replay_miss(self, after_sequence: int, boot_id: str | None = None) -> str:
        if boot_id is not None and boot_id != self._boot_id:
            return "boot_mismatch"
        if after_sequence < 0:
            return "invalid_sequence"
        if after_sequence > self.latest_sequence:
            return "future_sequence"
        if not self._history:
            return "empty_history"
        if after_sequence < self._history[0].sequence - 1:
            return "too_old"
        return "unknown"

    def prune_stale_subscribers(self, *, max_idle_seconds: int = 300) -> int:
        now = datetime.now(timezone.utc)
        stale_ids = [
            queue_id
            for queue_id, subscriber in self._subscribers.items()
            if self._is_stale_subscriber(subscriber, now=now, max_idle_seconds=max_idle_seconds)
        ]
        for queue_id in stale_ids:
            self._subscribers.pop(queue_id, None)
        self._pruned_subscriber_count += len(stale_ids)
        return len(stale_ids)

    @property
    def boot_id(self) -> str:
        return self._boot_id

    @property
    def latest_sequence(self) -> int:
        return self._next_sequence - 1

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def websocket_subscriber_count(self) -> int:
        return sum(1 for subscriber in self._subscribers.values() if subscriber.kind == "websocket")

    @property
    def queued_event_count(self) -> int:
        return sum(subscriber.queue.qsize() for subscriber in self._subscribers.values())

    @property
    def dropped_event_count(self) -> int:
        return sum(subscriber.dropped_events for subscriber in self._subscribers.values())

    def stats(self) -> EventBusStats:
        websocket_subscribers = [
            subscriber for subscriber in self._subscribers.values() if subscriber.kind == "websocket"
        ]
        internal_subscribers = [
            subscriber for subscriber in self._subscribers.values() if subscriber.kind == "internal"
        ]
        queue_depths = [subscriber.queue.qsize() for subscriber in self._subscribers.values()]
        return EventBusStats(
            subscriber_count=self.subscriber_count,
            queued_event_count=self.queued_event_count,
            dropped_event_count=self.dropped_event_count,
            published_event_count=self._published_event_count,
            replay_event_count=self._replay_event_count,
            history_size=len(self._history),
            replay_oldest_sequence=self._history[0].sequence if self._history else None,
            latest_sequence=self.latest_sequence,
            stream_reset_count=self._stream_reset_count,
            websocket_queue_depth=sum(subscriber.queue.qsize() for subscriber in websocket_subscribers),
            internal_queue_depth=sum(subscriber.queue.qsize() for subscriber in internal_subscribers),
            max_subscriber_queue_depth=max(queue_depths, default=0),
            websocket_dropped_event_count=sum(subscriber.dropped_events for subscriber in websocket_subscribers),
            replay_miss_count=self._replay_miss_count,
            replay_miss_reasons=dict(sorted(self._replay_miss_reasons.items())),
            snapshot_fallback_count=self._snapshot_fallback_count,
            stale_subscriber_count=sum(
                1
                for subscriber in self._subscribers.values()
                if self._is_stale_subscriber(
                    subscriber,
                    now=datetime.now(timezone.utc),
                    max_idle_seconds=300,
                )
            ),
            pruned_subscriber_count=self._pruned_subscriber_count,
        )

    def subscriber_snapshots(self) -> list[EventSubscriberSnapshot]:
        snapshots: list[EventSubscriberSnapshot] = []
        for subscriber in self._subscribers.values():
            snapshots.append(
                EventSubscriberSnapshot(
                    id=subscriber.id,
                    kind=subscriber.kind,
                    queue_depth=subscriber.queue.qsize(),
                    max_queue_size=subscriber.queue.maxsize,
                    dropped_events=subscriber.dropped_events,
                    stream_reset_count=subscriber.stream_reset_count,
                    created_at=subscriber.created_at,
                    last_enqueued_at=subscriber.last_enqueued_at,
                    last_overflow_at=subscriber.last_overflow_at,
                    categories=sorted(category.value for category in subscriber.categories or []),
                    event_types=sorted(subscriber.event_types or []),
                )
            )
        return snapshots

    def snapshot(self, *, recent_limit: int = 100) -> EventBusSnapshot:
        return EventBusSnapshot(
            stats=self.stats(),
            subscribers=self.subscriber_snapshots(),
            recent_events=self.recent_events(limit=recent_limit),
            observed_at=datetime.now(timezone.utc),
        )

    def _coerce_event(
        self,
        event: RuntimeEventEnvelope | dict[str, Any],
        *,
        correlation_id: str | None,
        causation_id: str | None,
    ) -> RuntimeEventEnvelope:
        if isinstance(event, RuntimeEventEnvelope):
            updates: dict[str, Any] = {}
            if correlation_id is not None:
                updates["correlation_id"] = correlation_id
            if causation_id is not None:
                updates["causation_id"] = causation_id
            return event.model_copy(update=updates) if updates else event

        payload = dict(event)
        if "category" not in payload and "type" in payload:
            payload["category"] = self._coerce_category(None, str(payload["type"]))
        if "source" not in payload:
            payload["source"] = {"component": "legacy"}
        if "correlation_id" not in payload:
            payload["correlation_id"] = correlation_id
        if "causation_id" not in payload:
            payload["causation_id"] = causation_id
        return RuntimeEventEnvelope.model_validate(payload)

    @staticmethod
    def _coerce_category(category: RuntimeEventCategory | str | None, event_type: str) -> RuntimeEventCategory:
        if category is not None:
            return RuntimeEventCategory(category)
        prefix = event_type.split(".", 1)[0]
        aliases = {"registry": RuntimeEventCategory.PLUGIN, "stream": RuntimeEventCategory.SYSTEM}
        if prefix in aliases:
            return aliases[prefix]
        return RuntimeEventCategory(prefix)

    @staticmethod
    def _coerce_source(source: RuntimeEventSource | dict[str, Any] | None) -> RuntimeEventSource:
        if isinstance(source, RuntimeEventSource):
            return source
        return RuntimeEventSource.model_validate(source or {"component": "event_bus"})

    @staticmethod
    def _matches_subscriber(envelope: RuntimeEventEnvelope, subscriber: EventSubscriber) -> bool:
        if subscriber.categories is not None and envelope.category not in subscriber.categories:
            return False
        if subscriber.event_types is not None and envelope.event_type not in subscriber.event_types:
            return False
        if subscriber.kind == "all":
            return True
        if subscriber.kind == "websocket":
            return envelope.visibility in {RuntimeEventVisibility.WEBSOCKET, RuntimeEventVisibility.BOTH}
        return envelope.visibility in {RuntimeEventVisibility.INTERNAL, RuntimeEventVisibility.BOTH}

    @staticmethod
    def _drain_queue(queue: asyncio.Queue[RuntimeEventEnvelope]) -> int:
        dropped = 0
        while True:
            try:
                queue.get_nowait()
                TypedEventBus._safe_task_done(queue)
                dropped += 1
            except asyncio.QueueEmpty:
                return dropped

    @staticmethod
    def _safe_task_done(queue: asyncio.Queue[RuntimeEventEnvelope]) -> None:
        try:
            queue.task_done()
        except ValueError:
            pass

    @staticmethod
    def _is_stale_subscriber(
        subscriber: EventSubscriber,
        *,
        now: datetime,
        max_idle_seconds: int,
    ) -> bool:
        if subscriber.last_overflow_at is None:
            return False
        if not subscriber.queue.full():
            return False
        age_seconds = (now - subscriber.last_overflow_at).total_seconds()
        return age_seconds >= max(max_idle_seconds, 0)

    @staticmethod
    def _stream_reset_event(*, sequence: int, causation_id: str, dropped_events: int) -> RuntimeEventEnvelope:
        return RuntimeEventEnvelope(
            sequence=sequence,
            type="stream.reset",
            category=RuntimeEventCategory.SYSTEM,
            level=RuntimeEventLevel.WARNING,
            message="subscriber queue overflowed; client should request a fresh snapshot",
            source=RuntimeEventSource(component="event_bus"),
            causation_id=causation_id,
            visibility=RuntimeEventVisibility.WEBSOCKET,
            persistence=RuntimeEventPersistence.EPHEMERAL,
            replayable=False,
            payload={"reason": "subscriber_overflow", "dropped_events": dropped_events},
        )


EventBus = TypedEventBus
