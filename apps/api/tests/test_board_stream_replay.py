from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from .runtime_test_harness import RuntimeTestHarness


@pytest.mark.asyncio
async def test_board_stream_rejects_replay_across_boot_mismatch() -> None:
    harness = await RuntimeTestHarness.create()
    try:
        with TestClient(harness.app) as client:
            with client.websocket_connect("/api/board/stream") as websocket:
                first = websocket.receive_json()
                assert first["type"] == "board.snapshot"
                assert first["payload"]["boot_id"] == harness.event_bus.boot_id
                last_seq = first["sequence"]

            # A reconnect with the same boot_id and a valid last_seq should be
            # treated as replayable (no snapshot fallback recorded).
            baseline_misses = harness.event_bus.stats().replay_miss_count
            with client.websocket_connect(
                f"/api/board/stream?last_seq={last_seq}&boot_id={harness.event_bus.boot_id}"
            ):
                pass
            assert harness.event_bus.stats().replay_miss_count == baseline_misses

            # A reconnect with a stale last_seq but a mismatched boot_id (simulating
            # a client that survived an API process restart) must not be replayed;
            # it should be classified as a boot_mismatch miss and fall back to a
            # fresh board.snapshot instead of replaying the wrong timeline.
            with client.websocket_connect(
                f"/api/board/stream?last_seq={last_seq}&boot_id=stale-boot-from-old-process"
            ) as websocket:
                message = websocket.receive_json()
                assert message["type"] == "board.snapshot"
                assert message["payload"]["boot_id"] == harness.event_bus.boot_id

            stats = harness.event_bus.stats()
            assert stats.replay_miss_reasons.get("boot_mismatch", 0) >= 1
    finally:
        await harness.close()
