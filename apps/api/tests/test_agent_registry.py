from __future__ import annotations

from datetime import datetime, timezone

import pytest

from gremlinboard_api.schemas.contracts import (
    AgentEntityType,
    AgentStatus,
    GenerationJobRead,
    GenerationJobStatus,
    RuntimeEventCategory,
)
from gremlinboard_api.services.agent_registry import AgentRegistry
from gremlinboard_api.services.event_bus import EventBus


def generation_job(
    *,
    job_id: str = "job-1",
    status: GenerationJobStatus = GenerationJobStatus.QUEUED,
    progress: int = 0,
    step: str = "queued",
) -> GenerationJobRead:
    now = datetime.now(timezone.utc)
    return GenerationJobRead(
        id=job_id,
        widget_id="ops_status",
        stage_id="stage-1",
        requested_provider_id="codex",
        provider_id="codex",
        status=status,
        current_step=step,
        progress=progress,
        idea=None,
        install_blocked=status not in {GenerationJobStatus.INSTALLED},
        artifact_version=1,
        selected_version="0.1.0",
        error_message="failed" if status == GenerationJobStatus.FAILED else None,
        created_at=now,
        updated_at=now,
        completed_at=now if status in {GenerationJobStatus.COMPLETED, GenerationJobStatus.FAILED} else None,
        artifacts=[],
        logs=[],
    )


@pytest.mark.asyncio
async def test_agent_registry_projects_generation_job_hierarchy_and_events() -> None:
    bus = EventBus()
    registry = AgentRegistry(event_bus=bus)

    queued = await registry.upsert_generation_job(generation_job())
    running = await registry.upsert_generation_job(
        generation_job(status=GenerationJobStatus.RUNNING, progress=40, step="scaffold")
    )
    waiting = await registry.upsert_generation_job(
        generation_job(status=GenerationJobStatus.REVIEW_REQUIRED, progress=100, step="review")
    )

    assert queued.status == AgentStatus.QUEUED
    assert running.status == AgentStatus.RUNNING
    assert waiting.status == AgentStatus.WAITING_FOR_REVIEW

    tree = await registry.tree()
    assert tree.total == 2
    assert tree.roots[0].agent.id == "local-generation"
    assert tree.roots[0].children[0].agent.id == "generation:job-1"

    events = await registry.recent_events()
    assert [event.event_type for event in events] == [
        "agent.created",
        "agent.started",
        "agent.waiting_for_review",
    ]
    assert bus.replay(categories=[RuntimeEventCategory.AGENT])[-1].event_type == "agent.waiting_for_review"


@pytest.mark.asyncio
async def test_agent_registry_recovery_rebuilds_from_generation_jobs_without_replaying_noise() -> None:
    bus = EventBus()
    registry = AgentRegistry(event_bus=bus)

    summary = await registry.recover_generation_jobs(
        [
            generation_job(job_id="job-1", status=GenerationJobStatus.INSTALLED, progress=100),
            generation_job(job_id="job-2", status=GenerationJobStatus.FAILED, progress=60),
        ]
    )

    assert summary.recovered_agents == 2
    assert summary.failed_agents == 1
    assert registry.summary().total_agents == 2
    assert registry.summary().failed_agents == 1
    assert await registry.recent_events() == []


@pytest.mark.asyncio
async def test_agent_registry_filters_agents_for_api_reconciliation() -> None:
    registry = AgentRegistry(event_bus=EventBus())
    await registry.recover_generation_jobs(
        [
            generation_job(job_id="active", status=GenerationJobStatus.RUNNING, progress=50),
            generation_job(job_id="review", status=GenerationJobStatus.REVIEW_REQUIRED, progress=100),
            generation_job(job_id="done", status=GenerationJobStatus.INSTALLED, progress=100),
        ]
    )

    waiting = await registry.list_agents(status=AgentStatus.WAITING_FOR_REVIEW, type=AgentEntityType.TASK)

    assert [agent.id for agent in waiting] == ["generation:review"]
