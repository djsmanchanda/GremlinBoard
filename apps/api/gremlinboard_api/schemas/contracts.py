from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TileSize(str, Enum):
    SMALL = "1x1"
    TALL = "1x2"
    MEDIUM = "2x2"
    WIDE = "4x2"
    HIGH = "2x4"
    LARGE = "4x4"

    @property
    def cols(self) -> int:
        return int(self.value.split("x")[0])

    @property
    def rows(self) -> int:
        return int(self.value.split("x")[1])


ALLOWED_TILE_SIZES = {size.value for size in TileSize}


class LifecycleState(str, Enum):
    CREATED = "created"
    INSTALLING = "installing"
    RUNNING = "running"
    PAUSED = "paused"
    EXPIRED = "expired"
    REMOVED = "removed"
    ERROR = "error"


class RefreshPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    interval_seconds: int = Field(ge=0)


class LifecyclePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stateful: bool
    expires: bool
    default_ttl_seconds: int | None = Field(default=None, ge=1)


class RuntimePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_timeout_seconds: int = Field(default=10, ge=1)
    refresh_timeout_seconds: int = Field(default=10, ge=1)
    heartbeat_timeout_seconds: int = Field(default=120, ge=1)
    max_retries: int = Field(default=3, ge=0)
    retry_backoff_seconds: int = Field(default=2, ge=1)
    stale_after_seconds: int = Field(default=300, ge=1)


class RendererTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str


class ServiceTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: str
    class_name: str


class WidgetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str = "0.1.0"
    name: str
    category: str
    description: str
    min_size: TileSize
    preferred_size: TileSize
    allowed_sizes: list[TileSize]
    refresh_policy: RefreshPolicy
    lifecycle_policy: LifecyclePolicy
    runtime_policy: RuntimePolicy = Field(default_factory=RuntimePolicy)
    permissions: list[str]
    renderer: RendererTarget
    service: ServiceTarget
    config_schema: str

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value or not value[0].isalpha():
            raise ValueError("widget id must start with a letter")
        return value

    @model_validator(mode="after")
    def validate_sizes(self) -> "WidgetManifest":
        allowed = {size.value for size in self.allowed_sizes}
        if self.min_size.value not in allowed:
            raise ValueError("min_size must be included in allowed_sizes")
        if self.preferred_size.value not in allowed:
            raise ValueError("preferred_size must be included in allowed_sizes")
        if any(size.value not in ALLOWED_TILE_SIZES for size in self.allowed_sizes):
            raise ValueError("manifest includes unsupported tile sizes")
        return self


class WidgetInstanceBase(BaseModel):
    widget_id: str
    title: str | None = None
    size: TileSize
    config: dict[str, Any] = Field(default_factory=dict)


class WidgetCreate(WidgetInstanceBase):
    pass


class WidgetResize(BaseModel):
    size: TileSize


class WidgetReorder(BaseModel):
    ordered_ids: list[str]


class WidgetConfigUpdate(BaseModel):
    title: str | None = None
    config: dict[str, Any] | None = None


class WidgetInstanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    board_id: str
    widget_id: str
    title: str
    size: TileSize
    position_index: int
    config: dict[str, Any]
    state: dict[str, Any]
    lifecycle_state: LifecycleState
    status_message: str | None = None
    freshness_at: datetime | None = None
    expires_at: datetime | None = None
    last_error: str | None = None
    last_heartbeat: datetime | None = None
    service_started_at: datetime | None = None
    service_uptime_seconds: int = 0
    restart_count: int = 0
    consecutive_failures: int = 0


class WidgetPluginRead(BaseModel):
    widget_id: str
    version: str
    enabled: bool
    installed: bool
    is_core: bool
    source_type: str
    source_ref: str | None = None
    installed_at: datetime | None = None
    updated_at: datetime | None = None
    last_error: str | None = None


class WidgetPluginVersionRead(BaseModel):
    widget_id: str
    version: str
    created_at: datetime
    is_rollback: bool


class BoardRead(BaseModel):
    id: str
    name: str
    widgets: list[WidgetInstanceRead]


class WidgetRegistryEntry(BaseModel):
    manifest: WidgetManifest
    config_schema: dict[str, Any]
    plugin: WidgetPluginRead | None = None


class HealthRead(BaseModel):
    status: str
    registry_size: int
    active_runners: int


class RuntimeLogRead(BaseModel):
    id: str
    widget_instance_id: str | None = None
    widget_id: str | None = None
    level: str
    event: str
    message: str
    context: dict[str, Any]
    created_at: datetime


class WidgetSpecDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    category: str
    description: str
    min_size: TileSize
    preferred_size: TileSize
    refresh_policy: dict[str, Any]
    source_type: str
    permissions: list[str]
    output_schema: dict[str, Any]
    renderer_type: str
    lifecycle_policy: dict[str, Any]


class WidgetSpecValidationRead(BaseModel):
    stage_id: str
    stage: str
    valid: bool
    notes: list[str]
    normalized_spec: dict[str, Any] | None = None
    manifest_preview: dict[str, Any]
    scaffold_preview: dict[str, Any]
    errors: list[dict[str, Any]] = Field(default_factory=list)


class SpecDocumentFormat(str, Enum):
    JSON = "json"
    YAML = "yaml"


class SpecDocumentValidateRequest(BaseModel):
    format: SpecDocumentFormat
    content: str


class WidgetPackagePayload(BaseModel):
    manifest: dict[str, Any]
    config_schema: dict[str, Any]
    backend_source: str
    renderer_source: str


class WidgetPluginInstallRequest(BaseModel):
    package: WidgetPackagePayload
    enabled: bool = True
    source_type: str = "manual"
    source_ref: str | None = None


class WidgetPluginUpdateRequest(BaseModel):
    package: WidgetPackagePayload
    source_ref: str | None = None


class WidgetPluginToggleRequest(BaseModel):
    enabled: bool


class WidgetPluginRollbackRequest(BaseModel):
    version: str


class AIProviderRead(BaseModel):
    provider_id: str
    label: str
    status: str
    supports_codegen: bool
    supports_review: bool


class GenerationPipelinePreviewRead(BaseModel):
    stage_id: str
    provider_id: str
    steps: list[dict[str, Any]]
    install_blocked: bool
