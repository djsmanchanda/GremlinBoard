import type { TileSize } from "@/lib/types";

/**
 * TypeScript mirror of the widget view-blueprint contract.
 *
 * Authoritative source: `schemas/widget-blueprint.schema.json` and the Pydantic
 * models in `apps/api/gremlinboard_api/schemas/blueprint.py`. Keep this in sync
 * with that contract; everything here is intentionally permissive on read so the
 * universal renderer degrades gracefully instead of crashing on malformed data.
 */

export type BlueprintGap = "none" | "sm" | "md";
export type BlueprintStatusColor = "critical" | "warn" | "ok" | "neutral";
export type BlueprintStatusMap = Record<string, BlueprintStatusColor>;
export type BlueprintTier = "compact" | "medium" | "wide" | "tall" | "large";

export interface BlueprintShowIf {
  path: string;
  op: "exists" | "eq" | "gt" | "lt";
  value?: unknown;
}

interface BlueprintNodeBase {
  show_if?: BlueprintShowIf;
}

export interface StackNode extends BlueprintNodeBase {
  type: "stack";
  gap?: BlueprintGap;
  children: BlueprintNode[];
}

export interface RowNode extends BlueprintNodeBase {
  type: "row";
  gap?: BlueprintGap;
  children: BlueprintNode[];
}

export interface GridNode extends BlueprintNodeBase {
  type: "grid";
  gap?: BlueprintGap;
  columns: number;
  children: BlueprintNode[];
}

export interface ScrollNode extends BlueprintNodeBase {
  type: "scroll";
  gap?: BlueprintGap;
  children: BlueprintNode[];
}

export interface StatNode extends BlueprintNodeBase {
  type: "stat";
  label: string;
  value_path: string;
  unit?: string;
  emphasis?: "primary" | "secondary";
  trend_path?: string;
  status_path?: string;
  status_map?: BlueprintStatusMap;
}

export interface TextNode extends BlueprintNodeBase {
  type: "text";
  value_path?: string;
  literal?: string;
  variant: "title" | "body" | "caption" | "mono";
}

export interface BadgeItem {
  label_path?: string;
  literal?: string;
  status_path?: string;
  status_map?: BlueprintStatusMap;
}

export interface BadgeRowNode extends BlueprintNodeBase {
  type: "badge_row";
  items: BadgeItem[];
}

export interface ListItem {
  primary_path: string;
  secondary_path?: string;
  meta_path?: string;
  status_path?: string;
  status_map?: BlueprintStatusMap;
}

export interface ListNode extends BlueprintNodeBase {
  type: "list";
  items_path: string;
  limit?: number;
  item: ListItem;
}

export interface TableColumn {
  header: string;
  value_path: string;
  align?: "left" | "center" | "right";
}

export interface TableNode extends BlueprintNodeBase {
  type: "table";
  items_path: string;
  limit?: number;
  columns: TableColumn[];
}

export interface KeyValueEntry {
  label: string;
  value_path: string;
}

export interface KeyValueNode extends BlueprintNodeBase {
  type: "key_value";
  entries?: KeyValueEntry[];
  entries_path?: string;
}

export interface ProgressNode extends BlueprintNodeBase {
  type: "progress";
  value_path: string;
  max_path?: string;
  max_literal?: number;
  label?: string;
}

export interface SparklineNode extends BlueprintNodeBase {
  type: "sparkline";
  values_path: string;
  label?: string;
}

export interface TimerNode extends BlueprintNodeBase {
  type: "timer";
  target_path: string;
  direction: "down" | "up";
  label_path?: string;
}

export interface EmptyStateNode extends BlueprintNodeBase {
  type: "empty_state";
  message: string;
  show_if_empty_path: string;
}

export type LayoutNode = StackNode | RowNode | GridNode | ScrollNode;
export type PrimitiveNode =
  | StatNode
  | TextNode
  | BadgeRowNode
  | ListNode
  | TableNode
  | KeyValueNode
  | ProgressNode
  | SparklineNode
  | TimerNode
  | EmptyStateNode;
export type BlueprintNode = LayoutNode | PrimitiveNode;

export interface BlueprintLayouts {
  compact?: BlueprintNode;
  medium: BlueprintNode;
  wide?: BlueprintNode;
  tall?: BlueprintNode;
  large?: BlueprintNode;
}

export interface Blueprint {
  blueprint_version: "1";
  widget_id: string;
  layouts: BlueprintLayouts;
  defaults?: Record<string, BlueprintNode>;
}

export const EM_DASH = "—";

const LAYOUT_TYPES = new Set(["stack", "row", "grid", "scroll"]);

export function isLayoutNode(node: BlueprintNode): node is LayoutNode {
  return LAYOUT_TYPES.has(node.type);
}

/**
 * Safe dot-path resolver. Accepts paths of the form `a.b[0].c` and returns the
 * resolved value or `undefined` — it never throws, whatever the shape of state.
 */
export function resolvePath(state: unknown, path: string): unknown {
  if (typeof path !== "string" || path.length === 0) {
    return undefined;
  }

  let current: unknown = state;
  for (const segment of path.split(".")) {
    const match = /^([A-Za-z_][A-Za-z0-9_]*)((?:\[[0-9]+\])*)$/.exec(segment);
    if (!match) {
      return undefined;
    }

    const key = match[1];
    if (current === null || typeof current !== "object") {
      return undefined;
    }
    current = (current as Record<string, unknown>)[key];

    const indexTokens = match[2].match(/\[[0-9]+\]/g);
    if (indexTokens) {
      for (const token of indexTokens) {
        const index = Number(token.slice(1, -1));
        if (!Array.isArray(current) || index < 0 || index >= current.length) {
          return undefined;
        }
        current = current[index];
      }
    }
  }

  return current;
}

function toComparableNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/** Evaluate a `show_if` guard against the widget state. Missing guard => visible. */
export function evaluateShowIf(state: unknown, showIf: BlueprintShowIf | undefined): boolean {
  if (!showIf) {
    return true;
  }

  const actual = resolvePath(state, showIf.path);
  switch (showIf.op) {
    case "exists":
      return actual !== undefined && actual !== null;
    case "eq":
      if (actual === showIf.value) {
        return true;
      }
      // Fall back to loose numeric comparison so 1 == "1" behaves intuitively.
      {
        const a = toComparableNumber(actual);
        const b = toComparableNumber(showIf.value);
        return a !== null && b !== null && a === b;
      }
    case "gt": {
      const a = toComparableNumber(actual);
      const b = toComparableNumber(showIf.value);
      return a !== null && b !== null && a > b;
    }
    case "lt": {
      const a = toComparableNumber(actual);
      const b = toComparableNumber(showIf.value);
      return a !== null && b !== null && a < b;
    }
    default:
      return true;
  }
}

/** Resolve a status color from a value + status map, `null` when unmapped. */
export function resolveStatusColor(
  state: unknown,
  statusPath: string | undefined,
  statusMap: BlueprintStatusMap | undefined,
): BlueprintStatusColor | null {
  if (!statusPath || !statusMap) {
    return null;
  }
  const raw = resolvePath(state, statusPath);
  if (raw === undefined || raw === null) {
    return null;
  }
  const key = typeof raw === "string" ? raw : String(raw);
  return statusMap[key] ?? null;
}

const SIZE_TO_TIER: Record<TileSize, BlueprintTier> = {
  "1x1": "compact",
  "1x2": "medium",
  "2x2": "medium",
  "4x2": "wide",
  "2x4": "tall",
  "4x4": "large",
};

// Nearest-smaller fallback chains; `medium` is always defined so every chain ends there.
const TIER_FALLBACK: Record<BlueprintTier, BlueprintTier[]> = {
  compact: ["compact", "medium"],
  medium: ["medium"],
  wide: ["wide", "medium"],
  tall: ["tall", "medium"],
  large: ["large", "wide", "tall", "medium"],
};

export function sizeToTier(size: TileSize): BlueprintTier {
  return SIZE_TO_TIER[size] ?? "medium";
}

export interface ResolvedLayout {
  tier: BlueprintTier;
  node: BlueprintNode;
}

/** Map a widget size to a concrete layout node, applying nearest-smaller fallback. */
export function resolveLayout(blueprint: Blueprint, size: TileSize): ResolvedLayout | null {
  const tier = sizeToTier(size);
  const layouts = blueprint.layouts;
  if (!layouts || typeof layouts !== "object") {
    return null;
  }
  for (const candidate of TIER_FALLBACK[tier]) {
    const node = layouts[candidate];
    if (node) {
      return { tier: candidate, node };
    }
  }
  return layouts.medium ? { tier: "medium", node: layouts.medium } : null;
}

/**
 * Light structural validation of a raw blueprint document. Returns the typed
 * blueprint or `null` when the shape is unusable (so the renderer can show a
 * muted fallback instead of crashing). Full schema validation happens on the
 * backend at install time.
 */
export function parseBlueprint(raw: unknown): Blueprint | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return null;
  }
  const candidate = raw as Record<string, unknown>;
  if (candidate.blueprint_version !== "1") {
    return null;
  }
  const layouts = candidate.layouts;
  if (!layouts || typeof layouts !== "object" || Array.isArray(layouts)) {
    return null;
  }
  const medium = (layouts as Record<string, unknown>).medium;
  if (!medium || typeof medium !== "object") {
    return null;
  }
  return candidate as unknown as Blueprint;
}
