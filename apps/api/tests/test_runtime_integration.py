from __future__ import annotations

import importlib
from collections import Counter

import pytest

from gremlinboard_api.repositories.board import BoardRepository
from gremlinboard_api.schemas.contracts import LifecycleState

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
