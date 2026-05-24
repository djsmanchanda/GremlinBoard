from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from gremlinboard_api.schemas.contracts import PresenceSource, RuntimePowerState
from gremlinboard_api.services.event_bus import EventBus
from gremlinboard_api.services.presence import PresenceManager


@pytest.mark.asyncio
async def test_presence_manager_transitions_between_idle_and_active() -> None:
    now = datetime(2026, 5, 24, tzinfo=timezone.utc)
    bus = EventBus()
    manager = PresenceManager(
        event_bus=bus,
        board_id="default",
        idle_after_seconds=90,
        clock=lambda: now,
    )

    initial = await manager.snapshot()
    assert initial.state == RuntimePowerState.IDLE
    assert await manager.should_pause_scheduled_work() is True

    active = await manager.record_activity(PresenceSource.BOARD_FETCH)
    assert active.state == RuntimePowerState.ACTIVE
    assert await manager.should_pause_scheduled_work() is False

    now += timedelta(seconds=91)
    idle = await manager.snapshot()
    assert idle.state == RuntimePowerState.IDLE
    assert idle.reason == "no recent operator presence"

    transitions = [event.event_type for event in bus.replay(after_sequence=0)]
    assert transitions == ["runtime.idle_entered", "runtime.active_entered", "runtime.idle_entered"]


@pytest.mark.asyncio
async def test_presence_manager_tracks_websocket_connections() -> None:
    bus = EventBus()
    manager = PresenceManager(event_bus=bus, board_id="default")

    token = await manager.websocket_connected()
    snapshot = await manager.snapshot()

    assert token
    assert snapshot.state == RuntimePowerState.ACTIVE
    assert snapshot.active_websocket_count == 1

    disconnected = await manager.websocket_disconnected(token)
    assert disconnected.active_websocket_count == 0


@pytest.mark.asyncio
async def test_presence_manager_suspend_and_resume_are_explicit_power_states() -> None:
    bus = EventBus()
    manager = PresenceManager(event_bus=bus, board_id="default")

    suspended = await manager.suspend(reason="tray requested suspend")
    assert suspended.state == RuntimePowerState.SUSPENDED
    assert suspended.suspended is True
    assert await manager.should_pause_scheduled_work() is True

    resumed = await manager.resume(source=PresenceSource.CLI)
    assert resumed.state == RuntimePowerState.ACTIVE
    assert resumed.suspended is False
    assert resumed.active_sources[-1].source == PresenceSource.CLI


@pytest.mark.asyncio
async def test_presence_manager_degraded_state_overrides_activity_without_suspending() -> None:
    bus = EventBus()
    manager = PresenceManager(event_bus=bus, board_id="default")

    await manager.record_activity(PresenceSource.OPERATOR)
    degraded = await manager.snapshot(degraded=True, reason="provider backoff")

    assert degraded.state == RuntimePowerState.DEGRADED
    assert degraded.degraded is True
    assert await manager.should_pause_scheduled_work() is False
