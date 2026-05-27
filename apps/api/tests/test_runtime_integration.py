from __future__ import annotations

import importlib
from collections import Counter

import pytest

from gremlinboard_api.repositories.board import BoardRepository
from gremlinboard_api.schemas.contracts import GenerationJobRead, GenerationJobStatus, LifecycleState

from .runtime_test_harness import (
    RuntimeTestHarness,
    build_crashy_widget_package,
    build_persistent_widget_package,
    write_widget_package,
)


async def _write_and_sync_package(harness: RuntimeTestHarness, package: dict[str, object]) -> None:
    write_widget_package(harness.widgets_dir, str(package["manifest"]["id"]), package)
    harness.registry.load()
    await harness.plugin_manager.sync_with_filesystem()


def _metric_value(metrics: list[dict[str, object]], *, metric_name: str, scope_type: str) -> int | None:
    for metric in metrics:
        if metric["metric_name"] == metric_name and metric["scope_type"] == scope_type:
            return int(metric["metric_value"])
    return None


def _generation_job_read(*, job_id: str, status: GenerationJobStatus, progress: int) -> GenerationJobRead:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return GenerationJobRead(
        id=job_id,
        widget_id="agent_status_widget",
        stage_id="stage-1",
        requested_provider_id="codex",
        provider_id="codex",
        status=status,
        current_step=status.value,
        progress=progress,
        idea=None,
        install_blocked=status != GenerationJobStatus.INSTALLED,
        artifact_version=1,
        selected_version="0.1.0",
        error_message=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
        artifacts=[],
        logs=[],
    )


@pytest.mark.asyncio
async def test_widget_lifecycle_create_start_persist_remove_keeps_runtime_and_db_consistent() -> None:
    harness = await RuntimeTestHarness.create()
    try:
        notes = [
            {"id": "1", "text": "Check runtime health"},
            {"id": "2", "text": "Confirm rollback snapshot"},
        ]
        package = build_persistent_widget_package(
            package_name=harness.package_name,
            widget_id="sticky_notes",
            version="1.0.0",
        )
        await _write_and_sync_package(harness, package)

        response = await harness.client.post(
            "/api/board/widgets",
            json={
                "widget_id": "sticky_notes",
                "title": "Ops Notes",
                "size": "2x2",
                "config": {"notes": notes},
            },
        )
        assert response.status_code == 200
        widget_id = response.json()["id"]

        running = await harness.wait_for_widget(
            widget_id,
            predicate=lambda widget: widget.lifecycle_state == LifecycleState.RUNNING
            and widget.state.get("notes") == notes,
        )

        assert running.status_message == "running"
        assert running.state["manifest_version"] == "1.0.0"
        assert harness.runtime_manager.active_count == 1

        board_response = await harness.client.get("/api/board")
        assert board_response.status_code == 200
        assert board_response.json()["widgets"][0]["state"]["notes"] == notes

        started_log = await harness.wait_for_log(
            predicate=lambda log: log.widget_instance_id == widget_id and log.event == "runner.started"
        )
        assert started_log.widget_id == "sticky_notes"

        remove_response = await harness.client.delete(f"/api/board/widgets/{widget_id}")
        assert remove_response.status_code == 200

        async with harness.session_factory() as session:
            repository = BoardRepository(session)
            record = await repository.get_widget(widget_id)
            assert record is not None
            assert record.is_removed is True
            assert record.lifecycle_state == LifecycleState.REMOVED.value

        final_board = await harness.client.get("/api/board")
        assert final_board.status_code == 200
        assert final_board.json()["widgets"] == []
        assert harness.runtime_manager.active_count == 0
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_runtime_failure_retries_with_backoff_and_emits_terminal_observability() -> None:
    harness = await RuntimeTestHarness.create()
    try:
        package = build_crashy_widget_package(
            package_name=harness.package_name,
            widget_id="crashy_widget",
        )
        await _write_and_sync_package(harness, package)

        response = await harness.client.post(
            "/api/board/widgets",
            json={
                "widget_id": "crashy_widget",
                "title": "Crash Loop",
                "size": "2x2",
                "config": {"crash_message": "refresh exploded"},
            },
        )
        assert response.status_code == 200
        widget_id = response.json()["id"]

        failed = await harness.wait_for_widget(
            widget_id,
            predicate=lambda widget: widget.lifecycle_state == LifecycleState.ERROR
            and widget.status_message == "runtime failed"
            and widget.last_error == "refresh exploded"
            and widget.restart_count == 2
            and widget.consecutive_failures == 3,
            timeout=8.0,
        )

        assert failed.state == {}

        crash_module = importlib.import_module(f"{harness.package_name}.crashy_widget.backend")
        start_timestamps = crash_module.START_TIMESTAMPS
        assert len(start_timestamps) == 3
        assert start_timestamps[1] - start_timestamps[0] >= 0.9
        assert start_timestamps[2] - start_timestamps[1] >= 1.8

        await harness.wait_for_log(
            predicate=lambda log: log.widget_id == "crashy_widget"
            and log.event == "runner.refresh_failed"
            and log.level == "error"
        )

        logs = await harness.logs(widget_id="crashy_widget")
        failure_logs = [log for log in logs if log.event == "runner.refresh_failed"]
        start_logs = [log for log in logs if log.event == "runner.started"]

        assert len(start_logs) == 3
        assert Counter(log.level for log in failure_logs) == Counter({"error": 1, "warning": 2})

        await harness.observability.capture_runtime_snapshot()

        overview_response = await harness.client.get("/api/observability/overview", params={"limit": 20})
        assert overview_response.status_code == 200
        overview = overview_response.json()

        assert overview["summary"]["widgets_error"] == 1
        assert _metric_value(overview["metrics"], metric_name="widgets_error", scope_type="board") == 1
        assert _metric_value(overview["metrics"], metric_name="restart_count", scope_type="widget") == 2

        error_logs_response = await harness.client.get(
            "/api/observability/logs",
            params={"limit": 20, "level": "error", "widget_id": "crashy_widget"},
        )
        assert error_logs_response.status_code == 200
        assert error_logs_response.json()[0]["event"] == "runner.refresh_failed"
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_runtime_status_reports_control_plane_snapshot() -> None:
    harness = await RuntimeTestHarness.create()
    try:
        package = build_persistent_widget_package(
            package_name=harness.package_name,
            widget_id="status_widget",
            version="1.0.0",
        )
        await _write_and_sync_package(harness, package)

        create_response = await harness.client.post(
            "/api/board/widgets",
            json={
                "widget_id": "status_widget",
                "title": "Status Widget",
                "size": "2x2",
                "config": {"notes": [{"id": "1", "text": "visible runtime"}]},
            },
        )
        assert create_response.status_code == 200
        widget_id = create_response.json()["id"]
        await harness.wait_for_widget(
            widget_id,
            predicate=lambda widget: widget.lifecycle_state == LifecycleState.RUNNING,
        )

        status_response = await harness.client.get("/api/runtime/status")
        assert status_response.status_code == 200
        payload = status_response.json()

        assert payload["state"] == "active"
        assert payload["presence"]["state"] == "active"
        assert payload["presence"]["active_sources"][0]["source"] == "operator"
        assert payload["active_runners"] == 1
        assert payload["websocket_subscribers"] == 0
        assert payload["monitor_cadence_seconds"] == 60
        assert payload["queue_depth"] == 0
        assert payload["registry_size"] == 1
        assert payload["widgets_total"] == 1
        assert payload["startup_recovery"]["registry_size"] == 0
        assert payload["runners"][0]["instance_id"] == widget_id
        assert payload["runners"][0]["widget_id"] == "status_widget"
        assert payload["runners"][0]["refresh_mode"] == "manual"
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_runtime_status_passive_probe_does_not_keep_runtime_active() -> None:
    harness = await RuntimeTestHarness.create()
    try:
        status_response = await harness.client.get(
            "/api/runtime/status",
            headers={"x-gremlin-presence-passive": "true"},
        )
        assert status_response.status_code == 200
        payload = status_response.json()

        assert payload["state"] == "idle"
        assert payload["presence"]["state"] == "idle"
        assert payload["presence"]["reason"] == "no recent operator presence"
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_devtools_snapshot_exposes_replay_queue_and_provider_state() -> None:
    harness = await RuntimeTestHarness.create()
    try:
        await harness.event_bus.publish_event(
            "runtime.devtools_probe",
            category="runtime",
            source={"component": "test"},
            payload={"detail": "bounded"},
        )

        response = await harness.client.get("/api/devtools/snapshot")

        assert response.status_code == 200
        payload = response.json()
        assert payload["runtime"]["state"] == "active"
        assert payload["replay"]["latest_sequence"] >= 1
        probe_events = [
            event for event in payload["replay"]["recent_events"] if event["type"] == "runtime.devtools_probe"
        ]
        assert probe_events
        assert probe_events[-1]["payload_keys"] == ["detail"]
        assert "durability_notes" in payload["queues"]
        assert payload["queues"]["generation_worker_running"] is True
        assert payload["providers"]["cache"]["max_entries"] >= 1
        assert payload["pressure"]["queue_health"] in {"ok", "pressure", "overflow"}
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_devtools_actions_clear_replay_and_simulate_stream_reset() -> None:
    harness = await RuntimeTestHarness.create()
    try:
        await harness.event_bus.publish_event(
            "runtime.devtools_probe",
            category="runtime",
            source={"component": "test"},
        )

        clear_response = await harness.client.post("/api/devtools/actions/clear-replay")
        assert clear_response.status_code == 200
        assert clear_response.json()["detail"]["cleared_events"] >= 1
        assert harness.event_bus.stats().history_size == 0

        reset_response = await harness.client.post("/api/devtools/actions/simulate-stream-reset")
        assert reset_response.status_code == 200
        assert reset_response.json()["detail"]["sequence"] >= 1
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_agent_api_and_runtime_status_expose_agent_registry_snapshot() -> None:
    harness = await RuntimeTestHarness.create()
    try:
        await harness.agent_registry.upsert_generation_job(
            _generation_job_read(
                job_id="agent-job-1",
                status=GenerationJobStatus.REVIEW_REQUIRED,
                progress=100,
            )
        )

        agents_response = await harness.client.get("/api/agents")
        assert agents_response.status_code == 200
        assert {agent["id"] for agent in agents_response.json()} == {
            "local-generation",
            "generation:agent-job-1",
        }

        tree_response = await harness.client.get("/api/agents/tree")
        assert tree_response.status_code == 200
        tree = tree_response.json()
        assert tree["total"] == 2
        assert tree["roots"][0]["children"][0]["agent"]["status"] == "waiting_for_review"

        events_response = await harness.client.get("/api/agents/events")
        assert events_response.status_code == 200
        assert events_response.json()[0]["type"] == "agent.created"

        status_response = await harness.client.get("/api/runtime/status")
        assert status_response.status_code == 200
        status = status_response.json()
        assert status["state"] == "active"
        assert status["active_agents"] == 0
        assert status["agents_waiting_for_review"] == 1
        assert status["agents_failed"] == 0
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_plugin_rollback_restores_registry_plugin_and_runtime_state() -> None:
    harness = await RuntimeTestHarness.create()
    try:
        widget_id = "rollback_widget"
        version_one_package = build_persistent_widget_package(
            package_name=harness.package_name,
            widget_id=widget_id,
            version="1.0.0",
        )

        install_response = await harness.client.post(
            "/api/plugins/install",
            json={
                "package": version_one_package,
                "enabled": True,
                "source_type": "manual",
            },
        )
        assert install_response.status_code == 200
        assert install_response.json()["is_core"] is False

        create_response = await harness.client.post(
            "/api/board/widgets",
            json={
                "widget_id": widget_id,
                "title": "Rollback Candidate",
                "size": "2x2",
                "config": {"notes": [{"id": "1", "text": "v1"}]},
            },
        )
        assert create_response.status_code == 200
        instance_id = create_response.json()["id"]

        initial = await harness.wait_for_widget(
            instance_id,
            predicate=lambda widget: widget.lifecycle_state == LifecycleState.RUNNING
            and widget.state.get("manifest_version") == "1.0.0",
        )
        assert initial.service_started_at is not None
        initial_started_at = initial.service_started_at

        version_two_package = build_persistent_widget_package(
            package_name=harness.package_name,
            widget_id=widget_id,
            version="2.0.0",
        )
        update_response = await harness.client.post(
            f"/api/plugins/{widget_id}/update",
            json={"package": version_two_package},
        )
        assert update_response.status_code == 200
        assert update_response.json()["version"] == "2.0.0"

        updated = await harness.wait_for_widget(
            instance_id,
            predicate=lambda widget: widget.lifecycle_state == LifecycleState.RUNNING
            and widget.state.get("manifest_version") == "2.0.0"
            and widget.service_started_at is not None
            and widget.service_started_at > initial_started_at,
        )
        assert updated.service_started_at is not None
        updated_started_at = updated.service_started_at

        assert harness.registry.get(widget_id).manifest.version == "2.0.0"
        assert (await harness.plugin_manager.get_plugin(widget_id)).version == "2.0.0"

        rollback_response = await harness.client.post(
            f"/api/plugins/{widget_id}/rollback",
            json={"version": "1.0.0"},
        )
        assert rollback_response.status_code == 200
        assert rollback_response.json()["source_type"] == "rollback"

        rolled_back = await harness.wait_for_widget(
            instance_id,
            predicate=lambda widget: widget.lifecycle_state == LifecycleState.RUNNING
            and widget.state.get("manifest_version") == "1.0.0"
            and widget.service_started_at is not None
            and widget.service_started_at > updated_started_at,
        )

        plugin = await harness.plugin_manager.get_plugin(widget_id)
        versions = await harness.plugin_manager.list_versions(widget_id)

        assert rolled_back.service_started_at is not None
        assert harness.registry.get(widget_id).manifest.version == "1.0.0"
        assert plugin is not None
        assert plugin.version == "1.0.0"
        assert plugin.source_type == "rollback"
        assert any(version.version == "1.0.0" and version.is_rollback for version in versions)
        assert harness.runtime_manager.active_count == 1

        restart_logs = [
            log
            for log in await harness.logs(widget_id=widget_id)
            if log.event == "runner.restarted"
        ]
        assert {log.context["reason"] for log in restart_logs} >= {"plugin updated", "plugin rolled back"}
    finally:
        await harness.close()
