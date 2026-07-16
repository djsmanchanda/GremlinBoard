from __future__ import annotations

import pytest

from gremlinboard_api.schemas.contracts import (
    RuntimeEventCategory,
    RuntimeEventEnvelope,
    RuntimeEventPersistence,
    RuntimeEventSource,
    RuntimeEventVisibility,
)
from gremlinboard_api.services.event_bus import EventBus


def test_event_envelope_validates_category_prefix() -> None:
    event = RuntimeEventEnvelope(
        type="widget.started",
        category=RuntimeEventCategory.WIDGET,
        source=RuntimeEventSource(component="runtime_manager", widget_instance_id="w1"),
    )

    assert event.event_type == "widget.started"
    assert event.to_websocket_message()["type"] == "widget.started"

    with pytest.raises(ValueError, match="event category must match"):
        RuntimeEventEnvelope(
            type="widget.started",
            category=RuntimeEventCategory.RUNTIME,
            source=RuntimeEventSource(component="runtime_manager"),
        )


@pytest.mark.asyncio
async def test_event_bus_fanout_isolates_subscribers_and_counts_drops() -> None:
    bus = EventBus(default_queue_size=2)
    fast = bus.subscribe(kind="internal")
    slow = bus.subscribe(kind="internal", max_queue_size=1)

    await bus.publish_event("runtime.started", category="runtime", source={"component": "test"})
    await bus.publish_event("runtime.monitor_tick", category="runtime", source={"component": "test"})

    assert (await fast.get()).event_type == "runtime.started"
    assert (await fast.get()).event_type == "runtime.monitor_tick"
    assert (await slow.get()).event_type == "runtime.monitor_tick"
    assert bus.dropped_event_count == 1


@pytest.mark.asyncio
async def test_websocket_overflow_emits_stream_reset() -> None:
    bus = EventBus(default_queue_size=1)
    websocket = bus.subscribe(kind="websocket", max_queue_size=1)

    await bus.publish_event(
        "board.snapshot",
        category="board",
        source={"component": "test"},
        payload={"id": "board", "widgets": []},
        visibility=RuntimeEventVisibility.WEBSOCKET,
    )
    await bus.publish_event(
        "board.snapshot",
        category="board",
        source={"component": "test"},
        payload={"id": "board", "widgets": []},
        visibility=RuntimeEventVisibility.WEBSOCKET,
    )

    reset = await websocket.get()

    assert reset.event_type == "stream.reset"
    assert reset.payload["reason"] == "subscriber_overflow"
    assert bus.dropped_event_count == 1
    stats = bus.stats()
    assert stats.stream_reset_count == 1
    assert stats.websocket_dropped_event_count == 1
    assert stats.max_subscriber_queue_depth == 0


@pytest.mark.asyncio
async def test_event_bus_replay_is_bounded_by_sequence() -> None:
    bus = EventBus(history_size=2)
    first = await bus.publish_event("runtime.started", category="runtime", source={"component": "test"})
    second = await bus.publish_event("widget.started", category="widget", source={"component": "test"})
    third = await bus.publish_event("generation.completed", category="generation", source={"component": "test"})

    assert bus.can_replay(second.sequence - 1)
    assert not bus.can_replay(first.sequence - 1)
    assert not bus.can_replay(third.sequence + 1)
    assert [event.event_type for event in bus.replay(after_sequence=second.sequence)] == [third.event_type]
    assert bus.stats().replay_oldest_sequence == second.sequence
    assert bus.stats().latest_sequence == third.sequence


@pytest.mark.asyncio
async def test_websocket_replay_excludes_internal_only_events() -> None:
    bus = EventBus()
    internal_event = await bus.publish_event(
        "runtime.started",
        category="runtime",
        source={"component": "test"},
        visibility=RuntimeEventVisibility.INTERNAL,
    )
    websocket_event = await bus.publish_event(
        "board.snapshot",
        category="board",
        source={"component": "test"},
        visibility=RuntimeEventVisibility.WEBSOCKET,
        payload={"id": "board", "widgets": []},
    )

    replayed = bus.replay(after_sequence=internal_event.sequence - 1, kind="websocket")

    assert [event.event_type for event in replayed] == [websocket_event.event_type]


@pytest.mark.asyncio
async def test_ephemeral_events_are_replayable_but_not_persistence_marked() -> None:
    bus = EventBus()
    event = await bus.publish_event(
        "provider.backoff_started",
        category="provider",
        source={"component": "provider_runtime", "provider_id": "newsapi"},
        persistence=RuntimeEventPersistence.TIMELINE,
        payload={"backoff_seconds": 30},
    )

    assert event.persistence == RuntimeEventPersistence.TIMELINE
    assert bus.replay(after_sequence=event.sequence - 1)[0].id == event.id


def test_event_bus_classifies_and_counts_replay_misses() -> None:
    bus = EventBus(history_size=2)

    bus.record_replay_miss(bus.classify_replay_miss(-1))
    bus.record_replay_miss(bus.classify_replay_miss(10))

    stats = bus.stats()
    assert stats.replay_miss_count == 2
    assert stats.replay_miss_reasons == {
        "future_sequence": 1,
        "invalid_sequence": 1,
    }


@pytest.mark.asyncio
async def test_event_bus_prunes_stale_overflowed_subscribers() -> None:
    bus = EventBus(default_queue_size=1)
    websocket = bus.subscribe(kind="websocket", max_queue_size=1)

    await bus.publish_event(
        "board.snapshot",
        category="board",
        source={"component": "test"},
        payload={"id": "board", "widgets": []},
        visibility=RuntimeEventVisibility.WEBSOCKET,
    )
    await bus.publish_event(
        "board.snapshot",
        category="board",
        source={"component": "test"},
        payload={"id": "board", "widgets": []},
        visibility=RuntimeEventVisibility.WEBSOCKET,
    )

    assert bus.prune_stale_subscribers(max_idle_seconds=0) == 1
    assert bus.websocket_subscriber_count == 0
    assert bus.stats().pruned_subscriber_count == 1
    bus.unsubscribe(websocket)


def test_event_bus_boot_id_defaults_to_random_and_is_stable() -> None:
    bus = EventBus()
    assert isinstance(bus.boot_id, str)
    assert bus.boot_id
    assert bus.boot_id == bus.boot_id

    other = EventBus()
    assert other.boot_id != bus.boot_id


def test_event_bus_accepts_fixed_boot_id() -> None:
    bus = EventBus(boot_id="fixed-boot-id")
    assert bus.boot_id == "fixed-boot-id"


@pytest.mark.asyncio
async def test_can_replay_rejects_mismatched_boot_id_regardless_of_sequence() -> None:
    bus = EventBus(boot_id="boot-a", history_size=4)
    event = await bus.publish_event("runtime.started", category="runtime", source={"component": "test"})

    # a sequence that would otherwise be replayable
    assert bus.can_replay(event.sequence - 1)
    # but a mismatched boot_id unconditionally rejects it
    assert not bus.can_replay(event.sequence - 1, "boot-b")
    # matching boot_id still allows replay
    assert bus.can_replay(event.sequence - 1, "boot-a")


def test_can_replay_omitted_boot_id_is_unaffected() -> None:
    bus = EventBus(boot_id="boot-a")
    # no history published yet; behavior should match the sequence-only rules
    assert bus.can_replay(0)
    assert not bus.can_replay(-1)


def test_classify_replay_miss_reports_boot_mismatch() -> None:
    bus = EventBus(boot_id="boot-a", history_size=4)

    assert bus.classify_replay_miss(0, "boot-b") == "boot_mismatch"
    assert bus.classify_replay_miss(0, "boot-a") != "boot_mismatch"
    assert bus.classify_replay_miss(-1) == "invalid_sequence"
