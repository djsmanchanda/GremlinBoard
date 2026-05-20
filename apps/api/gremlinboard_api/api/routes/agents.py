from __future__ import annotations

from fastapi import APIRouter, Query, Request

from gremlinboard_api.schemas.contracts import (
    AgentEntity,
    AgentEntityType,
    AgentStatus,
    AgentTreeRead,
    RuntimeEventEnvelope,
)


router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentEntity])
async def list_agents(
    request: Request,
    status: AgentStatus | None = Query(default=None),
    type: AgentEntityType | None = Query(default=None),
    source: str | None = Query(default=None),
) -> list[AgentEntity]:
    return await request.app.state.agent_registry.list_agents(
        status=status,
        type=type,
        source=source,
    )


@router.get("/tree", response_model=AgentTreeRead)
async def agent_tree(
    request: Request,
    status: AgentStatus | None = Query(default=None),
    type: AgentEntityType | None = Query(default=None),
    source: str | None = Query(default=None),
) -> AgentTreeRead:
    return await request.app.state.agent_registry.tree(
        status=status,
        type=type,
        source=source,
    )


@router.get("/events", response_model=list[RuntimeEventEnvelope])
async def agent_events(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: AgentStatus | None = Query(default=None),
    type: AgentEntityType | None = Query(default=None),
    source: str | None = Query(default=None),
) -> list[RuntimeEventEnvelope]:
    return await request.app.state.agent_registry.recent_events(
        limit=limit,
        status=status,
        type=type,
        source=source,
    )
