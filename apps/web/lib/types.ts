export type TileSize = "1x1" | "1x2" | "2x2" | "4x2" | "2x4" | "4x4";
export type LifecycleState = "created" | "installing" | "running" | "paused" | "expired" | "removed" | "error";
export type WidgetPermission = "network" | "storage" | "credentials" | "long_running" | "realtime_stream" | "passive_widget";
export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface RefreshPolicy {
  mode: "manual" | "interval" | "live";
  interval_seconds: number;
}

export interface ModuleRendererTarget {
  /** Backend emits "module"; older payloads/mocks may omit the discriminator. */
  kind?: "module";
  target: "react";
  module: string;
  export_name: string;
}

export interface BlueprintRendererTarget {
  kind: "blueprint";
  blueprint: "view.blueprint.json";
}

export type RendererTarget = ModuleRendererTarget | BlueprintRendererTarget;

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
  permissions: WidgetPermission[];
  renderer: RendererTarget;
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
  blueprint?: JsonObject | null;
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
  blueprint?: JsonObject | null;
}

export interface BoardState {
  id: string;
  name: string;
  owner_user_id?: string | null;
  widgets: WidgetInstance[];
}

export interface BoardPatch {
  board_id: string;
  name?: string | null;
  owner_user_id?: string | null;
  upserted_widgets?: WidgetInstance[];
  removed_widget_ids?: string[];
  ordered_widget_ids?: string[];
}

export interface RuntimeEventMessage<TPayload = JsonObject> {
  type: string;
  id?: string;
  sequence?: number;
  schema_version?: number;
  category?: string;
  level?: string;
  message?: string | null;
  source?: JsonObject;
  correlation_id?: string | null;
  causation_id?: string | null;
  visibility?: string;
  persistence?: string;
  replayable?: boolean;
  created_at?: string;
  payload?: TPayload;
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
  model_options: AIModelOption[];
  model_catalog_source: string;
  model_catalog_status: string;
}

export interface AIModelOption {
  id: string;
  label?: string | null;
  intelligence_level?: string | null;
  speed_level?: string | null;
  reasoning_effort_options: string[];
  source: string;
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
  | "completed"
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

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  calls: number;
}

export interface GenerationJob {
  id: string;
  widget_id: string;
  stage_id?: string | null;
  requested_provider_id?: string | null;
  provider_id: string;
  status: GenerationJobStatus;
  current_step?: string | null;
  /** Stage progress 0-100 emitted by the pipeline; used for the inline progress line. */
  progress?: number | null;
  idea?: string | null;
  generation_mode?: string | null;
  model_id?: string | null;
  token_usage?: TokenUsage | null;
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

export interface GenerationFeedbackRequest {
  feedback: string;
  provider_id?: string;
  model_id?: string;
  reasoning_effort?: string;
  fallback_provider_ids?: string[];
}

export interface GenerationFeedbackResponse {
  category: string;
  metadata?: JsonObject;
  job: GenerationJob;
  test_box?: GenerationTestBox | null;
}

export interface GenerationTestBox {
  job_id: string;
  widget_id: string;
  stage_id?: string | null;
  name: string;
  description: string;
  category: string;
  size: TileSize;
  allowed_sizes: TileSize[];
  manifest: JsonObject;
  config_schema: JsonObject;
  renderer: JsonObject;
  service: JsonObject;
  initial_config: JsonObject;
  initial_state: JsonObject;
  files: GenerationArtifactFile[];
  install_blocked: boolean;
  review_required: boolean;
}

export interface EasyGenerationJob {
  job: GenerationJob;
  test_box?: GenerationTestBox | null;
  feedback_categories: Array<"name" | "sizing" | "ui" | "feature">;
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

export interface PresenceSourceSnapshot {
  source: string;
  active: number;
  last_seen_at?: string | null;
}

export interface PresenceSnapshot {
  state: "active" | "idle" | "suspended" | "degraded";
  active_sources: PresenceSourceSnapshot[];
  active_websocket_count: number;
  recent_interaction_at?: string | null;
  idle_after_seconds: number;
  suspended: boolean;
  degraded: boolean;
  reason?: string | null;
  updated_at: string;
}

export interface ProviderDegradation {
  provider_id: string;
  label?: string | null;
  status: string;
  error?: string | null;
  widget_instance_id?: string | null;
  widget_id?: string | null;
  fallback_used: boolean;
  stale: boolean;
}

export interface RuntimeRunnerStatus {
  instance_id: string;
  widget_id: string;
  manifest_version: string;
  running: boolean;
  refresh_mode: string;
  refresh_interval_seconds: number;
  restart_count: number;
  consecutive_failures: number;
  last_started_at?: string | null;
  last_heartbeat_at?: string | null;
  last_refresh_at?: string | null;
}

export interface RuntimeStartupRecovery {
  recovered_widgets: number;
  skipped_widgets: number;
  orphan_widgets: number;
  registry_size: number;
  checked_at?: string | null;
}

export interface RuntimeStatus {
  state: "active" | "idle" | "suspended" | "degraded";
  presence?: PresenceSnapshot | null;
  active_runners: number;
  websocket_subscribers: number;
  monitor_cadence_seconds: number;
  provider_degradation: ProviderDegradation[];
  queue_depth: number;
  dropped_event_count: number;
  replay_event_count: number;
  published_event_count: number;
  replay_history_size: number;
  replay_oldest_sequence?: number | null;
  latest_sequence: number;
  stream_reset_count: number;
  replay_miss_count: number;
  replay_miss_reasons: Record<string, number>;
  snapshot_fallback_count: number;
  websocket_queue_depth: number;
  internal_queue_depth: number;
  max_subscriber_queue_depth: number;
  websocket_dropped_event_count: number;
  stale_subscriber_count: number;
  pruned_subscriber_count: number;
  observability_sink_error?: string | null;
  registry_size: number;
  widgets_total: number;
  active_agents: number;
  agents_waiting_for_review: number;
  agents_failed: number;
  runners: RuntimeRunnerStatus[];
  startup_recovery: RuntimeStartupRecovery;
}

export interface DevtoolsSubscriber {
  id: string;
  kind: "internal" | "websocket" | "all";
  queue_depth: number;
  max_queue_size: number;
  dropped_events: number;
  stream_reset_count: number;
  created_at: string;
  last_enqueued_at?: string | null;
  last_overflow_at?: string | null;
  categories: string[];
  event_types: string[];
  health: "ok" | "pressure" | "overflow";
}

export interface DevtoolsEventSummary {
  id: string;
  sequence: number;
  type: string;
  category: string;
  level: string;
  visibility: string;
  persistence: string;
  replayable: boolean;
  source: JsonObject;
  correlation_id?: string | null;
  causation_id?: string | null;
  created_at: string;
  payload_keys: string[];
  payload_size: number;
}

export interface RuntimeDevtoolsSnapshot {
  observed_at: string;
  runtime: RuntimeStatus;
  replay: {
    history_size: number;
    replay_oldest_sequence?: number | null;
    latest_sequence: number;
    replay_event_count: number;
    replay_miss_count: number;
    replay_miss_reasons: Record<string, number>;
    stream_reset_count: number;
    snapshot_fallback_count: number;
    recent_events: DevtoolsEventSummary[];
  };
  websocket: {
    subscriber_count: number;
    subscribers: DevtoolsSubscriber[];
    stream_reset_count: number;
    replay_miss_count: number;
    snapshot_fallback_count: number;
  };
  queues: {
    event_bus_queue_depth: number;
    websocket_queue_depth: number;
    internal_queue_depth: number;
    generation_queue_depth: number;
    generation_queued_input_count: number;
    generation_worker_running: boolean;
    max_subscriber_queue_depth: number;
    dropped_event_count: number;
    websocket_dropped_event_count: number;
    stale_subscriber_count: number;
    pruned_subscriber_count: number;
    observability_sink_error?: string | null;
    health: "ok" | "pressure" | "overflow";
    durability_notes: Record<string, string>;
  };
  providers: {
    providers: Array<{
      provider_id: string;
      active_requests: number;
      total_requests: number;
      coalesced_requests: number;
      cooldown_skips: number;
      cache_hits: number;
      cache_misses: number;
      stale_fallbacks: number;
      fallback_responses: number;
      errors: number;
      last_status: string;
      last_error?: string | null;
      last_started_at?: string | null;
      last_finished_at?: string | null;
      consecutive_failures: number;
      cooldown_until?: string | null;
    }>;
    coordination: {
      inflight_request_count: number;
      max_inflight_requests: number;
      inflight_keys: string[];
      oldest_inflight_started_at?: string | null;
      coalesced_request_count: number;
    };
    cache: {
      entry_count: number;
      max_entries: number;
      expired_entry_count: number;
      stale_retention_seconds: number;
      namespace_counts: Record<string, number>;
    };
    degradation: ProviderDegradation[];
  };
  pressure: {
    queue_health: "ok" | "pressure" | "overflow";
    replay_pressure: "ok" | "pressure";
    subscriber_pressure: "ok" | "pressure" | "overflow";
    provider_pressure: "ok" | "degraded";
    stale_widget_count: number;
    error_widget_count: number;
  };
}
