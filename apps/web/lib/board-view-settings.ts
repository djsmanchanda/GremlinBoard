import type { JsonObject, WidgetInstance, WidgetManifest, WidgetPlugin } from "@/lib/types";

export type BoardMode = "view" | "edit";
export type BoardDensityPreset = "wall-monitor" | "half-display" | "operator-desk";
export type WidgetAlertLevel = "critical" | "alert" | "completed" | "nominal";

export interface BoardViewSettings {
  mode: BoardMode;
  density: BoardDensityPreset;
  showStats: boolean;
}

export interface BoardDensityDefinition {
  label: string;
  description: string;
  targetCellPx: number;
  minCellPx: number;
  gridMinWidthPx: number;
  cardTone: "broadcast" | "condensed" | "operator";
}

export interface WidgetProviderState {
  provider_id?: string;
  label?: string;
  status?: string;
  error?: string | null;
}

export interface WidgetAlert {
  level: WidgetAlertLevel;
  rank: number;
  label: string;
  reasons: string[];
}

export const BOARD_VIEW_SETTINGS_STORAGE_KEY = "gremlinboard.board-view-settings.v1";

export const BOARD_DENSITY_PRESETS: Record<BoardDensityPreset, BoardDensityDefinition> = {
  "wall-monitor": {
    label: "Wall monitor",
    description: "Larger cells for glanceable room displays.",
    targetCellPx: 264,
    minCellPx: 184,
    gridMinWidthPx: 920,
    cardTone: "broadcast",
  },
  "half-display": {
    label: "Half display",
    description: "Tighter cells for a side-by-side operations screen.",
    targetCellPx: 184,
    minCellPx: 136,
    gridMinWidthPx: 720,
    cardTone: "condensed",
  },
  "operator-desk": {
    label: "Operator desk",
    description: "Balanced density for active triage and editing.",
    targetCellPx: 224,
    minCellPx: 160,
    gridMinWidthPx: 760,
    cardTone: "operator",
  },
};

export const DEFAULT_BOARD_VIEW_SETTINGS: BoardViewSettings = {
  mode: "view",
  density: "operator-desk",
  showStats: false,
};

const ALERT_RANK: Record<WidgetAlertLevel, number> = {
  nominal: 0,
  completed: 1,
  alert: 2,
  critical: 3,
};

export function readBoardViewSettings(): BoardViewSettings {
  if (typeof window === "undefined") {
    return DEFAULT_BOARD_VIEW_SETTINGS;
  }

  try {
    const raw = window.localStorage.getItem(BOARD_VIEW_SETTINGS_STORAGE_KEY);
    if (!raw) {
      return DEFAULT_BOARD_VIEW_SETTINGS;
    }
    const parsed = JSON.parse(raw) as Partial<BoardViewSettings>;
    return {
      mode: isBoardMode(parsed.mode) ? parsed.mode : DEFAULT_BOARD_VIEW_SETTINGS.mode,
      density: isBoardDensityPreset(parsed.density) ? parsed.density : DEFAULT_BOARD_VIEW_SETTINGS.density,
      showStats: typeof parsed.showStats === "boolean" ? parsed.showStats : DEFAULT_BOARD_VIEW_SETTINGS.showStats,
    };
  } catch {
    return DEFAULT_BOARD_VIEW_SETTINGS;
  }
}

export function writeBoardViewSettings(settings: BoardViewSettings) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(BOARD_VIEW_SETTINGS_STORAGE_KEY, JSON.stringify(settings));
}

export function getWidgetProviderStates(widget: WidgetInstance): WidgetProviderState[] {
  const meta = typeof widget.state.meta === "object" && widget.state.meta ? (widget.state.meta as JsonObject) : {};
  return Array.isArray(meta.providers) ? (meta.providers as WidgetProviderState[]) : [];
}

export function getWidgetAlert(widget: WidgetInstance, manifest: WidgetManifest, plugin?: WidgetPlugin | null): WidgetAlert {
  const reasons: string[] = [];
  let level: WidgetAlertLevel = "nominal";

  const push = (nextLevel: WidgetAlertLevel, reason: string) => {
    reasons.push(reason);
    if (ALERT_RANK[nextLevel] > ALERT_RANK[level]) {
      level = nextLevel;
    }
  };

  if (widget.lifecycle_state === "error") {
    push("critical", "Service error");
  } else if (widget.lifecycle_state === "paused" || (widget.lifecycle_state === "expired" && widget.widget_id !== "countdown")) {
    push("alert", widget.lifecycle_state === "paused" ? "Paused" : "Expired");
  } else if (widget.lifecycle_state === "installing") {
    push("alert", "Installing");
  }

  if (widget.state.complete === true) {
    push("completed", "Completed successfully");
  }
  if (widget.last_error) {
    push("critical", "Runtime failure");
  }
  if (plugin?.last_error) {
    push("critical", "Plugin failure");
  }
  if (widget.consecutive_failures >= 3) {
    push("critical", `${widget.consecutive_failures} consecutive failures`);
  } else if (widget.consecutive_failures > 0) {
    push("alert", `${widget.consecutive_failures} recent failures`);
  }

  const staleAfterSeconds = manifest.runtime_policy.stale_after_seconds;
  if (manifest.refresh_policy.mode === "interval" && staleAfterSeconds > 0) {
    if (!widget.freshness_at) {
      push("alert", "No freshness sample");
    } else {
      const freshTime = new Date(widget.freshness_at).getTime();
      if (!Number.isNaN(freshTime)) {
        const ageSeconds = (Date.now() - freshTime) / 1000;
        if (ageSeconds > staleAfterSeconds * 2) {
          push("critical", "Data stale");
        } else if (ageSeconds > staleAfterSeconds) {
          push("alert", "Data aging");
        }
      }
    }
  }

  if (widget.restart_count >= 5) {
    push("critical", "Restart spike");
  } else if (widget.restart_count >= 3) {
    push("alert", "Restart elevated");
  }

  for (const provider of getWidgetProviderStates(widget)) {
    const status = provider.status?.toLowerCase() ?? "";
    if (provider.error || /error|fail|down|unavailable|disabled/.test(status)) {
      push("critical", `${provider.label ?? provider.provider_id ?? "Provider"} failure`);
    } else if (/degrad|warn|throttle|rate/.test(status)) {
      push("alert", `${provider.label ?? provider.provider_id ?? "Provider"} degraded`);
    }
  }

  const uniqueReasons = Array.from(new Set(reasons));
  return {
    level,
    rank: ALERT_RANK[level],
    label: level === "nominal" ? "Nominal" : uniqueReasons[0] ?? "Attention",
    reasons: uniqueReasons,
  };
}

export function getAlertRank(level: WidgetAlertLevel) {
  return ALERT_RANK[level];
}

export function canManuallyRefreshWidget(manifest: WidgetManifest) {
  return manifest.refresh_policy.mode === "interval";
}

function isBoardMode(value: unknown): value is BoardMode {
  return value === "view" || value === "edit";
}

function isBoardDensityPreset(value: unknown): value is BoardDensityPreset {
  return value === "wall-monitor" || value === "half-display" || value === "operator-desk";
}
