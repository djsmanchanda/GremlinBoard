from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from gremlinboard_api.schemas.contracts import (
    AgentEntity,
    AgentEntityType,
    AgentRegistrySummaryRead,
    AgentSession,
    AgentStatus,
    AgentTask,
    AgentTreeNodeRead,
    AgentTreeRead,
    GenerationJobRead,
    GenerationJobStatus,
    RuntimeEventCategory,
    RuntimeEventEnvelope,
    RuntimeEventLevel,
    RuntimeEventPersistence,
    RuntimeEventSource,
    RuntimeEventVisibility,
)
from gremlinboard_api.services.event_bus import EventBus


GENERATION_SESSION_ID = "local-generation"


@dataclass(slots=True)
class AgentRecoverySummary:
    recovered_agents: int = 0
    failed_agents: int = 0
    waiting_for_review: int = 0
    orphan_agents: int = 0
    checked_at: datetime | None = None


class AgentRegistry:
    """Process-local read model for local agent and generation orchestration state."""

    def __init__(self, *, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self._lock = asyncio.Lock()
        self._agents: dict[str, AgentEntity] = {}
        self._recent_events: list[RuntimeEventEnvelope] = []
        self.recovery = AgentRecoverySummary()

    async def recover_generation_jobs(self, jobs: list[GenerationJobRead]) -> AgentRecoverySummary:
        async with self._lock:
            for agent_id, agent in list(self._agents.items()):
                if agent_id == GENERATION_SESSION_ID or agent.parent_id == GENERATION_SESSION_ID:
                    self._agents.pop(agent_id, None)
            self._ensure_generation_session_locked(now=_now())
            for job in jobs:
                task = self._generation_task_from_job(job)
                self._agents[task.id] = task
            self._refresh_generation_session_locked()
            summary = self._build_recovery_summary_locked()
            self.recovery = summary
            return summary

    async def upsert_generation_job(self, job: GenerationJobRead) -> AgentTask:
        events: list[tuple[str, AgentTask, AgentTask | None]] = []
        async with self._lock:
            self._ensure_generation_session_locked(now=_now())
            task = self._generation_task_from_job(job)
            previous = self._agents.get(task.id)
            previous_task = previous if isinstance(previous, AgentTask) else None
            self._agents[task.id] = task
            self._refresh_generation_session_locked()
            event_type = self._event_type_for_transition(previous_task, task)
            if event_type is not None:
                events.append((event_type, task, previous_task))

        for event_type, task, previous_task in events:
            await self._publish_agent_event(event_type, task, previous_task=previous_task)
        return task

    async def upsert_agent(self, agent: AgentEntity) -> AgentEntity:
        async with self._lock:
            self._agents[agent.id] = agent
            self._refresh_generation_session_locked()
            return agent

    async def get_agent(self, agent_id: str) -> AgentEntity | None:
        async with self._lock:
            return self._agents.get(agent_id)

    async def list_agents(
        self,
        *,
        status: AgentStatus | str | None = None,
        type: AgentEntityType | str | None = None,
        source: str | None = None,
    ) -> list[AgentEntity]:
        status_filter = AgentStatus(status) if status is not None else None
        type_filter = AgentEntityType(type) if type is not None else None
        async with self._lock:
            agents = list(self._agents.values())
        return [
            agent
            for agent in sorted(agents, key=_agent_sort_key)
            if (status_filter is None or agent.status == status_filter)
            and (type_filter is None or agent.type == type_filter)
            and (source is None or agent.source == source)
        ]

    async def tree(
        self,
        *,
        status: AgentStatus | str | None = None,
        type: AgentEntityType | str | None = None,
        source: str | None = None,
    ) -> AgentTreeRead:
        agents = await self.list_agents(status=status, type=type, source=source)
        included_ids = {agent.id for agent in agents}
        children_by_parent: dict[str | None, list[AgentEntity]] = {}
        for agent in agents:
            parent_id = agent.parent_id if agent.parent_id in included_ids else None
            children_by_parent.setdefault(parent_id, []).append(agent)

        def build_node(agent: AgentEntity) -> AgentTreeNodeRead:
            children = [
                build_node(child)
                for child in sorted(children_by_parent.get(agent.id, []), key=_agent_sort_key)
            ]
            return AgentTreeNodeRead(agent=agent, children=children)

        roots = [build_node(agent) for agent in sorted(children_by_parent.get(None, []), key=_agent_sort_key)]
        return AgentTreeRead(roots=roots, total=len(agents))

    async def recent_events(
        self,
        *,
        limit: int = 50,
        status: AgentStatus | str | None = None,
        type: AgentEntityType | str | None = None,
        source: str | None = None,
    ) -> list[RuntimeEventEnvelope]:
        status_filter = AgentStatus(status) if status is not None else None
        type_filter = AgentEntityType(type) if type is not None else None
        async with self._lock:
            events = list(self._recent_events)
        filtered = []
        for event in reversed(events):
            payload = event.payload
            if status_filter is not None and payload.get("status") != status_filter.value:
                continue
            if type_filter is not None and payload.get("type") != type_filter.value:
                continue
            if source is not None and payload.get("source") != source:
                continue
            filtered.append(event)
            if len(filtered) >= limit:
                break
        return list(reversed(filtered))

    def summary(self) -> AgentRegistrySummaryRead:
        agents = [agent for agent in self._agents.values() if agent.type != AgentEntityType.SESSION]
        return AgentRegistrySummaryRead(
            active_agents=sum(1 for agent in agents if agent.status in {AgentStatus.CREATED, AgentStatus.QUEUED, AgentStatus.RUNNING}),
            waiting_for_review=sum(1 for agent in agents if agent.status == AgentStatus.WAITING_FOR_REVIEW),
            failed_agents=sum(1 for agent in agents if agent.status == AgentStatus.FAILED),
            total_agents=len(agents),
        )

    async def _publish_agent_event(
        self,
        event_type: str,
        task: AgentTask,
        *,
        previous_task: AgentTask | None,
    ) -> None:
        persistence = RuntimeEventPersistence.EPHEMERAL
        level = RuntimeEventLevel.INFO
        if event_type in {"agent.completed", "agent.failed", "agent.cancelled", "agent.waiting_for_review"}:
            persistence = RuntimeEventPersistence.TIMELINE
        if event_type == "agent.failed":
            level = RuntimeEventLevel.ERROR
        elif event_type in {"agent.cancelled", "agent.waiting_for_review"}:
            level = RuntimeEventLevel.WARNING

        event = await self.event_bus.publish_event(
            event_type,
            category=RuntimeEventCategory.AGENT,
            level=level,
            message=_agent_event_message(event_type, task),
            source=RuntimeEventSource(
                component="agent_registry",
                agent_id=task.id,
                job_id=task.linked_jobs[0] if task.linked_jobs else None,
                widget_id=task.linked_widgets[0] if task.linked_widgets else None,
            ),
            correlation_id=task.correlation_id,
            causation_id=task.causation_id,
            visibility=RuntimeEventVisibility.BOTH,
            persistence=persistence,
            payload={
                "id": task.id,
                "parent_id": task.parent_id,
                "session_id": task.session_id,
                "name": task.name,
                "type": task.type.value,
                "source": task.source,
                "status": task.status.value,
                "previous_status": previous_task.status.value if previous_task is not None else None,
                "progress": task.progress,
                "previous_progress": previous_task.progress if previous_task is not None else None,
                "review_required": task.review_required,
                "linked_jobs": task.linked_jobs,
                "linked_widgets": task.linked_widgets,
                "metadata": task.metadata,
            },
        )
        async with self._lock:
            self._recent_events.append(event)
            self._recent_events = self._recent_events[-100:]

    def _ensure_generation_session_locked(self, *, now: datetime) -> AgentSession:
        existing = self._agents.get(GENERATION_SESSION_ID)
        if isinstance(existing, AgentSession):
            return existing
        session = AgentSession(
            id=GENERATION_SESSION_ID,
            parent_id=None,
            session_id=GENERATION_SESSION_ID,
            name="Local Generation",
            source="generation_pipeline",
            status=AgentStatus.CREATED,
            progress=0,
            created_at=now,
            updated_at=now,
            correlation_id=GENERATION_SESSION_ID,
            causation_id=None,
            metadata={"mode": "local_first", "role": "generation_session"},
        )
        self._agents[session.id] = session
        return session

    def _refresh_generation_session_locked(self) -> None:
        session = self._agents.get(GENERATION_SESSION_ID)
        if not isinstance(session, AgentSession):
            return
        tasks = [
            agent
            for agent in self._agents.values()
            if isinstance(agent, AgentTask) and agent.session_id == GENERATION_SESSION_ID
        ]
        active = [task for task in tasks if task.status in {AgentStatus.CREATED, AgentStatus.QUEUED, AgentStatus.RUNNING}]
        waiting = [task for task in tasks if task.status == AgentStatus.WAITING_FOR_REVIEW]
        failed = [task for task in tasks if task.status == AgentStatus.FAILED]
        if active:
            status = AgentStatus.RUNNING if any(task.status == AgentStatus.RUNNING for task in active) else AgentStatus.QUEUED
        elif waiting:
            status = AgentStatus.WAITING_FOR_REVIEW
        elif failed and len(failed) == len(tasks):
            status = AgentStatus.FAILED
        elif tasks:
            status = AgentStatus.COMPLETED
        else:
            status = AgentStatus.CREATED
        progress = round(sum(task.progress for task in tasks) / len(tasks)) if tasks else 0
        self._agents[session.id] = session.model_copy(
            update={
                "status": status,
                "progress": progress,
                "updated_at": max((task.updated_at for task in tasks), key=_timestamp_sort_value, default=session.updated_at),
                "metadata": {
                    **session.metadata,
                    "task_count": len(tasks),
                    "active_tasks": len(active),
                    "waiting_for_review": len(waiting),
                    "failed_tasks": len(failed),
                },
            }
        )

    def _build_recovery_summary_locked(self) -> AgentRecoverySummary:
        tasks = [agent for agent in self._agents.values() if isinstance(agent, AgentTask)]
        return AgentRecoverySummary(
            recovered_agents=len(tasks),
            failed_agents=sum(1 for task in tasks if task.status == AgentStatus.FAILED),
            waiting_for_review=sum(1 for task in tasks if task.status == AgentStatus.WAITING_FOR_REVIEW),
            orphan_agents=sum(1 for task in tasks if not task.linked_jobs),
            checked_at=_now(),
        )

    @staticmethod
    def _generation_task_from_job(job: GenerationJobRead) -> AgentTask:
        status = _generation_status_to_agent_status(job.status)
        task_id = f"generation:{job.id}"
        metadata: dict[str, Any] = {
            "generation_job_id": job.id,
            "generation_status": job.status.value,
            "current_step": job.current_step,
            "stage_id": job.stage_id,
            "provider_id": job.provider_id,
            "requested_provider_id": job.requested_provider_id,
            "artifact_version": job.artifact_version,
            "selected_version": job.selected_version,
            "install_blocked": job.install_blocked,
            "error_message": job.error_message,
        }
        if job.install_target is not None:
            metadata["install_target"] = job.install_target
        return AgentTask(
            id=task_id,
            parent_id=GENERATION_SESSION_ID,
            session_id=GENERATION_SESSION_ID,
            name=f"Generate {job.widget_id}",
            source="generation_pipeline",
            status=status,
            progress=job.progress,
            created_at=job.created_at,
            updated_at=job.updated_at,
            correlation_id=job.id,
            causation_id=None,
            metadata=metadata,
            linked_jobs=[job.id],
            linked_widgets=[job.widget_id],
            review_required=job.status == GenerationJobStatus.REVIEW_REQUIRED or job.install_blocked,
            artifacts=[
                {
                    "stage": artifact.stage,
                    "artifact_type": artifact.artifact_type,
                    "artifact_version": artifact.artifact_version,
                    "created_at": artifact.created_at.isoformat(),
                }
                for artifact in job.artifacts
            ],
        )

    @staticmethod
    def _event_type_for_transition(previous: AgentTask | None, task: AgentTask) -> str | None:
        if previous is None:
            return "agent.created"
        if previous.status != task.status:
            if task.status == AgentStatus.RUNNING:
                return "agent.started"
            if task.status == AgentStatus.WAITING_FOR_REVIEW:
                return "agent.waiting_for_review"
            if task.status == AgentStatus.COMPLETED:
                return "agent.completed"
            if task.status == AgentStatus.FAILED:
                return "agent.failed"
            if task.status == AgentStatus.CANCELLED:
                return "agent.cancelled"
        if previous.progress != task.progress or previous.metadata.get("current_step") != task.metadata.get("current_step"):
            return "agent.progress_updated"
        return None


def _generation_status_to_agent_status(status: GenerationJobStatus) -> AgentStatus:
    return {
        GenerationJobStatus.QUEUED: AgentStatus.QUEUED,
        GenerationJobStatus.RUNNING: AgentStatus.RUNNING,
        GenerationJobStatus.COMPLETED: AgentStatus.COMPLETED,
        GenerationJobStatus.REVIEW_REQUIRED: AgentStatus.WAITING_FOR_REVIEW,
        GenerationJobStatus.APPROVED: AgentStatus.WAITING_FOR_REVIEW,
        GenerationJobStatus.REJECTED: AgentStatus.CANCELLED,
        GenerationJobStatus.INSTALLED: AgentStatus.COMPLETED,
        GenerationJobStatus.FAILED: AgentStatus.FAILED,
    }[status]


def _agent_event_message(event_type: str, task: AgentTask) -> str:
    label = {
        "agent.created": "Agent task created.",
        "agent.started": "Agent task started.",
        "agent.progress_updated": "Agent task progress updated.",
        "agent.completed": "Agent task completed.",
        "agent.failed": "Agent task failed.",
        "agent.cancelled": "Agent task cancelled.",
        "agent.waiting_for_review": "Agent task is waiting for review.",
    }.get(event_type, event_type)
    return f"{label} {task.name}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _agent_sort_key(agent: AgentEntity) -> tuple[float, str]:
    return (_timestamp_sort_value(agent.created_at), agent.id)


def _timestamp_sort_value(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).timestamp()
