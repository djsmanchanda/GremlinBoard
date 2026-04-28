export type TileSize = "1x1" | "1x2" | "2x2" | "4x2" | "2x4" | "4x4";
export type LifecycleState = "created" | "installing" | "running" | "paused" | "expired" | "removed" | "error";
export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface RefreshPolicy {
  mode: "manual" | "interval" | "live";
  interval_seconds: number;
}

export interface WidgetManifest {
  id: string;
  version: string;
  name: string;
  category: string;
  description: string;
  min_size: TileSize;
  preferred_size: TileSize;
  allowed_sizes: TileSize[];
  refresh_policy: RefreshPolicy;
  lifecycle_policy: {
    stateful: boolean;
    expires: boolean;
    default_ttl_seconds: number | null;
  };
  runtime_policy: {
    start_timeout_seconds: number;
    refresh_timeout_seconds: number;
    heartbeat_timeout_seconds: number;
    max_retries: number;
    retry_backoff_seconds: number;
    stale_after_seconds: number;
  };
  permissions: string[];
  renderer: {
    target: "react";
    module: string;
    export_name: string;
  };
}

export interface WidgetPlugin {
  widget_id: string;
  version: string;
  enabled: boolean;
  installed: boolean;
  is_core: boolean;
  source_type: string;
  source_ref?: string | null;
  installed_at?: string | null;
  updated_at?: string | null;
  last_error?: string | null;
}

export interface WidgetRegistryEntry {
  manifest: WidgetManifest;
  config_schema: JsonObject;
  plugin?: WidgetPlugin | null;
}

export interface WidgetInstance {
  id: string;
  board_id: string;
  owner_user_id?: string | null;
  widget_id: string;
  title: string;
  size: TileSize;
  position_index: number;
  config: JsonObject;
  state: JsonObject;
  lifecycle_state: LifecycleState;
  status_message?: string | null;
  freshness_at?: string | null;
  expires_at?: string | null;
  last_error?: string | null;
  last_heartbeat?: string | null;
  service_started_at?: string | null;
  service_uptime_seconds: number;
  restart_count: number;
  consecutive_failures: number;
}

export interface BoardState {
  id: string;
  name: string;
  owner_user_id?: string | null;
  widgets: WidgetInstance[];
}

export interface WidgetRendererProps {
  widget: WidgetInstance;
  manifest: WidgetManifest;
  onUpdateConfig?: (config: JsonObject) => void | Promise<void>;
}

export interface WidgetPreset {
  key: string;
  label: string;
  widget_id: string;
  title: string;
  size: TileSize;
  config: JsonObject;
}

export interface SpecValidationResult {
  stage_id: string;
  stage: string;
  valid: boolean;
  notes: string[];
  normalized_spec?: JsonObject | null;
  manifest_preview: JsonObject;
  scaffold_preview: {
    files: string[];
    review_required: boolean;
    install_blocked: boolean;
    widget_root?: string;
  };
  errors: Array<{
    message: string;
    line?: number;
    column?: number;
    path?: string;
    type?: string;
  }>;
}

export interface AIProvider {
  provider_id: string;
  label: string;
  status: string;
  supports_codegen: boolean;
  supports_review: boolean;
  supports_idea_to_spec: boolean;
  supported_model_ids: string[];
  default_model_id?: string | null;
}

export interface GenerationPipelinePreview {
  stage_id: string;
  provider_id: string;
  steps: Array<{
    id: string;
    label: string;
    status: string;
  }>;
  install_blocked: boolean;
}

export type GenerationJobStatus =
  | "queued"
  | "running"
  | "review_required"
  | "approved"
  | "rejected"
  | "installed"
  | "failed";

export interface GenerationArtifactFile {
  path: string;
  language: string;
  content: string;
}

export interface GenerationArtifactDiff {
  path: string;
  changed: boolean;
  summary: string;
  diff: string;
}

export interface GenerationArtifact {
  stage: string;
  artifact_type: string;
  artifact_version: number;
  files: GenerationArtifactFile[];
  payload?: JsonObject | null;
  created_at: string;
}

export interface GenerationJobLog {
  id: string;
  level: string;
  step: string;
  message: string;
  context: JsonObject;
  created_at: string;
}

export interface GenerationJob {
  id: string;
  widget_id: string;
  stage_id?: string | null;
  requested_provider_id?: string | null;
  provider_id: string;
  status: GenerationJobStatus;
  current_step?: string | null;
  idea?: string | null;
  install_blocked: boolean;
  artifact_version: number;
  selected_version: string;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  artifacts: GenerationArtifact[];
  logs: GenerationJobLog[];
  install_target?: {
    action: "install" | "update";
    widget_id: string;
    current_version?: string | null;
    next_version: string;
  } | null;
  diff_preview: GenerationArtifactDiff[];
}

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface SessionContext {
  id: string;
  user_id: string;
  status: string;
  last_seen_at: string;
  expires_at: string;
  created_at: string;
}

export interface AuthContext {
  user: User;
  session: SessionContext;
}

export interface RuntimeSettingsSection {
  monitor_interval_seconds: number;
  metrics_retention_points: number;
  log_view_limit: number;
}

export interface AppearanceSettingsSection {
  theme_mode: string;
  board_density: string;
  show_grid_overlay: boolean;
  reduced_motion: boolean;
}

export interface AIProviderSettingsSection {
  default_provider_id: string;
  fallback_provider_ids: string[];
  enabled_provider_ids: string[];
}

export interface AppSettingsSection {
  board_label: string;
  command_box_hint: string;
}

export interface SystemSettings {
  runtime: RuntimeSettingsSection;
  appearance: AppearanceSettingsSection;
  ai: AIProviderSettingsSection;
  app: AppSettingsSection;
}

export interface ApiCredential {
  id: string;
  provider: string;
  label: string;
  masked_value: string;
  created_at: string;
  updated_at: string;
}

export interface RuntimeMetric {
  scope_type: string;
  scope_id?: string | null;
  metric_name: string;
  metric_value: number;
  tags: JsonObject;
  created_at: string;
}

export interface RuntimeLog {
  id: string;
  widget_instance_id?: string | null;
  widget_id?: string | null;
  level: string;
  event: string;
  message: string;
  context: JsonObject;
  created_at: string;
}

export interface WidgetHealth {
  widget_instance_id: string;
  widget_id: string;
  title: string;
  lifecycle_state: LifecycleState;
  status_message?: string | null;
  freshness_at?: string | null;
  last_error?: string | null;
  restart_count: number;
  consecutive_failures: number;
  service_uptime_seconds: number;
}

export interface ObservabilityOverview {
  collected_at: string;
  summary: Record<string, number>;
  metrics: RuntimeMetric[];
  widget_health: WidgetHealth[];
  timeline: RuntimeLog[];
}
