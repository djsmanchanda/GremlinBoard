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
  permissions: string[];
  renderer: {
    target: string;
  };
}

export interface WidgetRegistryEntry {
  manifest: WidgetManifest;
  config_schema: JsonObject;
}

export interface WidgetInstance {
  id: string;
  board_id: string;
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
}

export interface BoardState {
  id: string;
  name: string;
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
