from __future__ import annotations

from datetime import datetime
from enum import Enum
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from gremlinboard_api.specs.widget_ids import sanitize_widget_id, widget_service_module


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

    target: Literal["react"] = "react"
    module: str
    export_name: str


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
        return sanitize_widget_id(value)

    @model_validator(mode="after")
    def validate_sizes(self) -> "WidgetManifest":
        allowed = {size.value for size in self.allowed_sizes}
        if self.min_size.value not in allowed:
            raise ValueError("min_size must be included in allowed_sizes")
        if self.preferred_size.value not in allowed:
            raise ValueError("preferred_size must be included in allowed_sizes")
        if any(size.value not in ALLOWED_TILE_SIZES for size in self.allowed_sizes):
            raise ValueError("manifest includes unsupported tile sizes")
        self.service.module = widget_service_module(self.id)
        if self.renderer.module != f"@widgets/{self.id}/renderer":
            raise ValueError("renderer.module must point at the widget package renderer entry")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.renderer.export_name):
            raise ValueError("renderer.export_name must be a valid identifier")
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
    owner_user_id: str | None = None
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
    owner_user_id: str | None = None
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

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return sanitize_widget_id(value)

    @field_validator("name", "category", "description", "source_type", "renderer_type")
    @classmethod
    def trim_text_fields(cls, value: str) -> str:
        return " ".join(value.split())


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
    supports_idea_to_spec: bool
    supported_model_ids: list[str] = Field(default_factory=list)
    default_model_id: str | None = None


class GenerationJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    INSTALLED = "installed"
    FAILED = "failed"


class GenerationJobCreateRequest(BaseModel):
    provider_id: str | None = None
    model_id: str | None = None
    fallback_provider_ids: list[str] = Field(default_factory=list)
    stage_id: str | None = None
    idea: str | None = None
    regenerate_from_job_id: str | None = None
    version: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "GenerationJobCreateRequest":
        provided = [bool(self.stage_id), bool(self.idea), bool(self.regenerate_from_job_id)]
        if sum(provided) != 1:
            raise ValueError("exactly one of stage_id, idea, or regenerate_from_job_id must be provided")
        return self


class GenerationJobRejectRequest(BaseModel):
    reason: str = Field(min_length=1)


class GenerationJobFeedbackRequest(BaseModel):
    feedback: str = Field(min_length=1)
    provider_id: str | None = None
    model_id: str | None = None
    fallback_provider_ids: list[str] = Field(default_factory=list)

    @field_validator("feedback")
    @classmethod
    def trim_feedback(cls, value: str) -> str:
        return " ".join(value.split())


class EasyGenerationCreateRequest(BaseModel):
    idea: str = Field(min_length=1)
    provider_id: str | None = None
    model_id: str | None = None
    fallback_provider_ids: list[str] = Field(default_factory=list)
    version: str | None = None

    @field_validator("idea")
    @classmethod
    def trim_idea(cls, value: str) -> str:
        return " ".join(value.split())


class GenerationJobInstallRequest(BaseModel):
    enabled: bool = True


class GenerationJobLogRead(BaseModel):
    id: str
    level: str
    step: str
    message: str
    context: dict[str, Any]
    created_at: datetime


class RuntimeMetricRead(BaseModel):
    scope_type: str
    scope_id: str | None = None
    metric_name: str
    metric_value: int
    tags: dict[str, Any]
    created_at: datetime


class UserRead(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime


class SessionRead(BaseModel):
    id: str
    user_id: str
    status: str
    last_seen_at: datetime
    expires_at: datetime
    created_at: datetime


class AuthContextRead(BaseModel):
    user: UserRead
    session: SessionRead


class RuntimeSettingsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monitor_interval_seconds: int = Field(default=5, ge=1, le=60)
    metrics_retention_points: int = Field(default=120, ge=10, le=1000)
    log_view_limit: int = Field(default=200, ge=20, le=1000)


class AppearanceSettingsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_mode: str = "control"
    board_density: str = "comfortable"
    show_grid_overlay: bool = True
    reduced_motion: bool = False


class AIProviderSettingsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_provider_id: str = "codex"
    fallback_provider_ids: list[str] = Field(default_factory=lambda: ["claude"])
    enabled_provider_ids: list[str] = Field(default_factory=lambda: ["codex", "claude"])


class AppSettingsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    board_label: str = "GremlinBoard"
    command_box_hint: str = "Add widget"


class SystemSettingsRead(BaseModel):
    runtime: RuntimeSettingsSection
    appearance: AppearanceSettingsSection
    ai: AIProviderSettingsSection
    app: AppSettingsSection


class SystemSettingsUpdateRequest(BaseModel):
    runtime: RuntimeSettingsSection | None = None
    appearance: AppearanceSettingsSection | None = None
    ai: AIProviderSettingsSection | None = None
    app: AppSettingsSection | None = None


class ApiCredentialRead(BaseModel):
    id: str
    provider: str
    label: str
    masked_value: str
    created_at: datetime
    updated_at: datetime


class ApiCredentialUpsertRequest(BaseModel):
    provider: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: str = Field(min_length=1)


class WidgetHealthRead(BaseModel):
    widget_instance_id: str
    widget_id: str
    title: str
    lifecycle_state: LifecycleState
    status_message: str | None = None
    freshness_at: datetime | None = None
    last_error: str | None = None
    restart_count: int
    consecutive_failures: int
    service_uptime_seconds: int


class ObservabilityOverviewRead(BaseModel):
    collected_at: datetime
    summary: dict[str, int]
    metrics: list[RuntimeMetricRead]
    widget_health: list[WidgetHealthRead]
    timeline: list[RuntimeLogRead]


class GenerationArtifactFileRead(BaseModel):
    path: str
    language: str
    content: str


class GenerationArtifactDiffRead(BaseModel):
    path: str
    changed: bool
    summary: str
    diff: str


class GenerationArtifactRead(BaseModel):
    stage: str
    artifact_type: str
    artifact_version: int
    files: list[GenerationArtifactFileRead] = Field(default_factory=list)
    payload: dict[str, Any] | None = None
    created_at: datetime


class GenerationJobRead(BaseModel):
    id: str
    widget_id: str
    stage_id: str | None = None
    requested_provider_id: str | None = None
    provider_id: str
    status: GenerationJobStatus
    current_step: str | None = None
    progress: int = Field(default=0, ge=0, le=100)
    idea: str | None = None
    install_blocked: bool
    artifact_version: int
    selected_version: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    artifacts: list[GenerationArtifactRead] = Field(default_factory=list)
    logs: list[GenerationJobLogRead] = Field(default_factory=list)
    install_target: dict[str, Any] | None = None
    diff_preview: list[GenerationArtifactDiffRead] = Field(default_factory=list)


FeedbackCategory = Literal["name", "sizing", "ui", "feature"]


class GenerationTestBoxRead(BaseModel):
    job_id: str
    widget_id: str
    stage_id: str | None = None
    name: str
    description: str
    category: str
    size: TileSize
    allowed_sizes: list[TileSize]
    manifest: dict[str, Any]
    config_schema: dict[str, Any]
    renderer: dict[str, Any]
    service: dict[str, Any]
    initial_config: dict[str, Any] = Field(default_factory=dict)
    initial_state: dict[str, Any] = Field(default_factory=dict)
    files: list[GenerationArtifactFileRead] = Field(default_factory=list)
    install_blocked: bool = True
    review_required: bool = True


class EasyGenerationJobRead(BaseModel):
    job: GenerationJobRead
    test_box: GenerationTestBoxRead | None = None
    feedback_categories: list[FeedbackCategory] = Field(default_factory=lambda: ["name", "sizing", "ui", "feature"])


class GenerationJobFeedbackRead(BaseModel):
    category: FeedbackCategory
    metadata: dict[str, Any] = Field(default_factory=dict)
    job: GenerationJobRead
    test_box: GenerationTestBoxRead | None = None


class GenerationPipelinePreviewRead(BaseModel):
    stage_id: str
    provider_id: str
    steps: list[dict[str, Any]]
    install_blocked: bool
