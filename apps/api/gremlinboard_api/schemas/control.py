from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from gremlinboard_api.schemas.contracts import AgentEntityType, AgentStatus, TileSize


ControlActionStatus = Literal["completed", "approval_required", "approved", "rejected"]


class ControlActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    params: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="api", min_length=1)
    correlation_id: str | None = None
    causation_id: str | None = None


class ControlEmptyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ControlWidgetAddParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    widget_id: str = Field(min_length=1)
    title: str | None = None
    size: TileSize
    config: dict[str, Any] = Field(default_factory=dict)


class ControlWidgetInstanceParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    widget_instance_id: str = Field(min_length=1)


class ControlWidgetResizeParams(ControlWidgetInstanceParams):
    size: TileSize


class ControlWidgetSettingsParams(ControlWidgetInstanceParams):
    title: str | None = None
    config: dict[str, Any] | None = None


class ControlJobsListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    widget_id: str | None = None


class ControlAgentsListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AgentStatus | None = None
    type: AgentEntityType | None = None
    source: str | None = None


class ControlApprovalRead(BaseModel):
    id: str
    action_id: str
    params: dict[str, Any]
    source: str
    reason: str
    correlation_id: str
    causation_id: str | None = None
    requested_at: datetime
    status: Literal["pending", "approved", "rejected"] = "pending"
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class ControlActionResponse(BaseModel):
    action_id: str
    status: ControlActionStatus
    message: str
    payload: Any = None
    correlation_id: str
    causation_id: str | None = None
    event_id: str | None = None
    approval: ControlApprovalRead | None = None


class ControlActionDefinitionRead(BaseModel):
    action_id: str
    description: str
    input_schema: dict[str, Any]
    destructive: bool = False
    approval_required: bool = False


class ControlMcpToolRead(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    action_id: str
    destructive: bool = False
    approval_required: bool = False


class ControlMcpToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None
    causation_id: str | None = None


class ControlApprovalListRead(BaseModel):
    approvals: list[ControlApprovalRead]


class ControlApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = None
    source: str = Field(default="api", min_length=1)
    correlation_id: str | None = None
    causation_id: str | None = None


def new_control_correlation_id() -> str:
    return f"ctrl-{uuid4().hex}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
