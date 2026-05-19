from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
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


@dataclass(slots=True)
class EventBusStats:
    subscriber_count: int = 0
    queued_event_count: int = 0
    dropped_event_count: int = 0
    published_event_count: int = 0
    replay_event_count: int = 0
    history_size: int = 0


class TypedEventBus:
    def __init__(self, *, default_queue_size: int = 64, history_size: int = 128) -> None:
        self.default_queue_size = default_queue_size
        self._history: deque[RuntimeEventEnvelope] = deque(maxlen=history_size)
        self._subscribers: dict[int, EventSubscriber] = {}
        self._next_subscriber_id = 1
        self._next_sequence = 1
        self._published_event_count = 0
        self._replay_event_count = 0

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
                    subscriber.queue.put_nowait(
                        self._stream_reset_event(
                            sequence=envelope.sequence,
                            causation_id=envelope.id,
                            dropped_events=dropped,
                        )
                    )
                    continue
                try:
                    subscriber.queue.get_nowait()
                    subscriber.dropped_events += 1
                except asyncio.QueueEmpty:
                    pass
            try:
                subscriber.queue.put_nowait(envelope)
            except asyncio.QueueFull:
                subscriber.dropped_events += 1
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
                            subscriber.dropped_events += 1
                        except asyncio.QueueEmpty:
                            pass
                    try:
                        queue.put_nowait(event)
                        self._replay_event_count += 1
                    except asyncio.QueueFull:
                        subscriber.dropped_events += 1
        return queue

    def unsubscribe(self, queue: asyncio.Queue[RuntimeEventEnvelope]) -> None:
        self._subscribers.pop(id(queue), None)

    def replay(
        self,
        *,
        after_sequence: int = 0,
        categories: Iterable[RuntimeEventCategory | str] | None = None,
        event_types: Iterable[str] | None = None,
    ) -> list[RuntimeEventEnvelope]:
        category_filter = {RuntimeEventCategory(category) for category in categories} if categories else None
        event_type_filter = set(event_types) if event_types else None
        return [
            event
            for event in self._history
            if event.sequence > after_sequence
            and (category_filter is None or event.category in category_filter)
            and (event_type_filter is None or event.event_type in event_type_filter)
        ]

    def can_replay(self, after_sequence: int) -> bool:
        if after_sequence < 0:
            return False
        if not self._history:
            return after_sequence >= self.latest_sequence
        return after_sequence >= self._history[0].sequence - 1

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
        return EventBusStats(
            subscriber_count=self.subscriber_count,
            queued_event_count=self.queued_event_count,
            dropped_event_count=self.dropped_event_count,
            published_event_count=self._published_event_count,
            replay_event_count=self._replay_event_count,
            history_size=len(self._history),
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
                dropped += 1
            except asyncio.QueueEmpty:
                return dropped

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
