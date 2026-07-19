"use client";

import { useEffect, useState, type ReactElement } from "react";

import { refreshWidget } from "@/lib/api";
import {
  EM_DASH,
  evaluateShowIf,
  resolvePath,
  resolveStatusColor,
  type ActionButtonNode,
  type BadgeRowNode,
  type BlueprintStatusColor,
  type EmptyStateNode,
  type KeyValueNode,
  type ListNode,
  type ProgressNode,
  type SparklineNode,
  type StatNode,
  type TableNode,
  type TextNode,
  type TimerNode,
} from "@/lib/blueprint";
import type { JsonObject } from "@/lib/types";

/**
 * Design-system-native leaf primitives for the universal blueprint renderer.
 * Every primitive degrades gracefully: an unresolvable binding renders an
 * em-dash or is skipped, and nothing ever renders the literal string
 * "undefined".
 */

interface PrimitiveProps<TNode> {
  node: TNode;
  state: unknown;
  compact: boolean;
}

const STATUS_TEXT: Record<BlueprintStatusColor, string> = {
  critical: "text-critical",
  warn: "text-warn",
  ok: "text-ok",
  neutral: "text-slate-300",
};

const STATUS_DOT: Record<BlueprintStatusColor, string> = {
  critical: "bg-critical",
  warn: "bg-warn",
  ok: "bg-ok",
  neutral: "bg-slate-600",
};

const STATUS_CHIP: Record<BlueprintStatusColor, string> = {
  critical: "border-critical/30 bg-critical/10 text-critical",
  warn: "border-warn/30 bg-warn/10 text-warn",
  ok: "border-ok/30 bg-ok/10 text-ok",
  neutral: "border-edge bg-surface-inset text-slate-300",
};

/** Format a resolved value for display, never emitting "undefined"/"null". */
function displayValue(value: unknown): string {
  if (value === undefined || value === null) {
    return EM_DASH;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : EM_DASH;
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "string") {
    return value.length > 0 ? value : EM_DASH;
  }
  if (Array.isArray(value)) {
    return value.length > 0 ? value.map((entry) => displayValue(entry)).join(", ") : EM_DASH;
  }
  return EM_DASH;
}

function toArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function StatPrimitive({ node, state, compact }: PrimitiveProps<StatNode>) {
  const value = resolvePath(state, node.value_path);
  const status = resolveStatusColor(state, node.status_path, node.status_map);
  const valueClass = status ? STATUS_TEXT[status] : "text-slate-100";
  const primary = node.emphasis !== "secondary";
  const sizeClass = compact
    ? "text-lg leading-6"
    : primary
      ? "text-2xl leading-none"
      : "text-lg leading-6";

  let trend: "up" | "down" | null = null;
  if (node.trend_path) {
    const rawTrend = resolvePath(state, node.trend_path);
    const numericTrend = typeof rawTrend === "number" ? rawTrend : Number(rawTrend);
    if (Number.isFinite(numericTrend) && numericTrend !== 0) {
      trend = numericTrend > 0 ? "up" : "down";
    }
  }

  return (
    <div className="min-w-0">
      <p className="truncate text-[10px] uppercase tracking-[0.16em] text-slate-500">{node.label}</p>
      <p className={`mt-1 flex items-baseline gap-1 font-mono font-semibold tabular-nums ${valueClass} ${sizeClass}`}>
        <span className="truncate">{displayValue(value)}</span>
        {node.unit ? <span className="text-xs font-normal text-slate-500">{node.unit}</span> : null}
        {trend ? (
          <span className={trend === "up" ? "text-ok text-xs" : "text-critical text-xs"} aria-hidden>
            {trend === "up" ? "↑" : "↓"}
          </span>
        ) : null}
      </p>
    </div>
  );
}

export function TextPrimitive({ node, state }: PrimitiveProps<TextNode>) {
  const raw = node.literal !== undefined ? node.literal : resolvePath(state, node.value_path ?? "");
  const text = displayValue(raw);
  switch (node.variant) {
    case "title":
      return <p className="truncate text-sm font-medium text-slate-100">{text}</p>;
    case "caption":
      return <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{text}</p>;
    case "mono":
      return <p className="font-mono text-xs tabular-nums text-slate-200">{text}</p>;
    case "body":
    default:
      return <p className="text-xs leading-5 text-slate-300">{text}</p>;
  }
}

export function BadgeRowPrimitive({ node, state }: PrimitiveProps<BadgeRowNode>) {
  const chips = node.items
    .map((item, index) => {
      const raw = item.literal !== undefined ? item.literal : resolvePath(state, item.label_path ?? "");
      if (raw === undefined || raw === null || raw === "") {
        return null;
      }
      const status = resolveStatusColor(state, item.status_path, item.status_map) ?? "neutral";
      return (
        <span
          key={index}
          className={`inline-flex items-center rounded-control border px-2 py-0.5 text-[10px] uppercase tracking-[0.1em] ${STATUS_CHIP[status]}`}
        >
          {displayValue(raw)}
        </span>
      );
    })
    .filter((chip): chip is ReactElement => chip !== null);

  if (chips.length === 0) {
    return null;
  }
  return <div className="flex flex-wrap gap-1.5">{chips}</div>;
}

export function ListPrimitive({ node, state, compact }: PrimitiveProps<ListNode>) {
  const items = toArray(resolvePath(state, node.items_path));
  const limited = typeof node.limit === "number" ? items.slice(0, node.limit) : items;

  if (limited.length === 0) {
    return null;
  }

  return (
    <div className="divide-y divide-edge">
      {limited.map((entry, index) => {
        const primary = resolvePath(entry, node.item.primary_path);
        const secondary = node.item.secondary_path ? resolvePath(entry, node.item.secondary_path) : undefined;
        const meta = node.item.meta_path ? resolvePath(entry, node.item.meta_path) : undefined;
        const href = node.item.href_path ? resolvePath(entry, node.item.href_path) : undefined;
        const status = resolveStatusColor(entry, node.item.status_path, node.item.status_map);
        const rowClass = `flex items-center gap-2 ${compact ? "py-1.5" : "py-2"} first:pt-0`;
        const row = (
          <>
            {status ? <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${STATUS_DOT[status]}`} aria-hidden /> : null}
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-slate-100">{displayValue(primary)}</p>
              {secondary !== undefined && secondary !== null && secondary !== "" ? (
                <p className="truncate text-[10px] leading-4 text-slate-500">{displayValue(secondary)}</p>
              ) : null}
            </div>
            {meta !== undefined && meta !== null && meta !== "" ? (
              <span className="shrink-0 text-[10px] tabular-nums text-slate-400">{displayValue(meta)}</span>
            ) : null}
          </>
        );
        return typeof href === "string" && href.trim().length > 0 ? (
          <a
            key={index}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className={`${rowClass} transition hover:bg-white/[0.03] focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent/60`}
          >
            {row}
          </a>
        ) : (
          <div key={index} className={rowClass}>
            {row}
          </div>
        );
      })}
    </div>
  );
}

interface ActionButtonPrimitiveProps extends PrimitiveProps<ActionButtonNode> {
  widgetId: string;
  currentConfig: JsonObject;
  onUpdateConfig?: (config: JsonObject) => void | Promise<void>;
}

export function ActionButtonPrimitive({
  node,
  compact,
  widgetId,
  currentConfig,
  onUpdateConfig,
}: ActionButtonPrimitiveProps) {
  const [pending, setPending] = useState(false);
  const primary = node.style !== "secondary";
  const disabled = pending || (node.action === "config_patch" && !onUpdateConfig);
  const weightClass = primary
    ? "border-accent/30 bg-accent/10 text-accent hover:bg-accent/16"
    : "border-edge bg-surface-inset text-slate-300 hover:bg-surface-raised hover:text-slate-100";

  async function handleClick() {
    if (disabled) {
      return;
    }

    setPending(true);
    try {
      if (node.action === "refresh") {
        await refreshWidget(widgetId);
      } else if (onUpdateConfig) {
        await onUpdateConfig({ ...currentConfig, ...node.config_patch } as JsonObject);
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <button
      type="button"
      onClick={() => void handleClick().catch(() => undefined)}
      disabled={disabled}
      className={`inline-flex items-center justify-center rounded-control border font-medium uppercase tracking-[0.12em] transition disabled:cursor-not-allowed disabled:opacity-50 ${
        compact ? "px-2 py-1 text-[10px]" : "px-2.5 py-1.5 text-[10px]"
      } ${weightClass}`}
    >
      {pending ? `${node.label}...` : node.label}
    </button>
  );
}
const ALIGN_CLASS: Record<"left" | "center" | "right", string> = {
  left: "text-left",
  center: "text-center",
  right: "text-right",
};

export function TablePrimitive({ node, state }: PrimitiveProps<TableNode>) {
  const rows = toArray(resolvePath(state, node.items_path));
  const limited = typeof node.limit === "number" ? rows.slice(0, node.limit) : rows;

  return (
    <div className="overflow-x-auto overflow-hidden">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="border-b border-edge">
            {node.columns.map((column, index) => (
              <th
                key={index}
                className={`py-1.5 pr-3 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500 last:pr-0 ${
                  ALIGN_CLASS[column.align ?? "left"]
                }`}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-edge">
          {limited.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {node.columns.map((column, colIndex) => (
                <td
                  key={colIndex}
                  className={`truncate py-1.5 pr-3 tabular-nums text-slate-200 last:pr-0 ${ALIGN_CLASS[column.align ?? "left"]}`}
                >
                  {displayValue(resolvePath(row, column.value_path))}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface KeyValuePair {
  label: string;
  value: unknown;
}

export function KeyValuePrimitive({ node, state }: PrimitiveProps<KeyValueNode>) {
  let pairs: KeyValuePair[] = [];
  if (node.entries) {
    pairs = node.entries.map((entry) => ({ label: entry.label, value: resolvePath(state, entry.value_path) }));
  } else if (node.entries_path) {
    pairs = toArray(resolvePath(state, node.entries_path)).map((entry) => {
      const record = entry && typeof entry === "object" ? (entry as Record<string, unknown>) : {};
      return { label: displayValue(record.label), value: record.value };
    });
  }

  if (pairs.length === 0) {
    return null;
  }

  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
      {pairs.map((pair, index) => (
        <div key={index} className="col-span-2 grid grid-cols-subgrid items-baseline">
          <dt className="truncate text-[10px] uppercase tracking-[0.14em] text-slate-500">{pair.label}</dt>
          <dd className="truncate text-right text-xs tabular-nums text-slate-200">{displayValue(pair.value)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ProgressPrimitive({ node, state }: PrimitiveProps<ProgressNode>) {
  const rawValue = resolvePath(state, node.value_path);
  const value = typeof rawValue === "number" ? rawValue : Number(rawValue);
  let max = node.max_literal ?? 100;
  if (node.max_path) {
    const rawMax = resolvePath(state, node.max_path);
    const numericMax = typeof rawMax === "number" ? rawMax : Number(rawMax);
    if (Number.isFinite(numericMax) && numericMax > 0) {
      max = numericMax;
    }
  }

  const percent = Number.isFinite(value) && max > 0 ? Math.min(Math.max((value / max) * 100, 0), 100) : 0;

  return (
    <div>
      {node.label !== undefined || Number.isFinite(value) ? (
        <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-[0.14em] text-slate-500">
          <span className="truncate">{node.label ?? ""}</span>
          <span className="tabular-nums text-slate-400">{Number.isFinite(value) ? `${Math.round(percent)}%` : EM_DASH}</span>
        </div>
      ) : null}
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-edge">
        <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

export function SparklinePrimitive({ node, state }: PrimitiveProps<SparklineNode>) {
  const values = toArray(resolvePath(state, node.values_path))
    .map((entry) => (typeof entry === "number" ? entry : Number(entry)))
    .filter((entry) => Number.isFinite(entry));

  if (values.length < 2) {
    return null;
  }

  const width = 100;
  const height = 24;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - ((value - min) / span) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <div className="text-accent">
      {node.label ? <p className="mb-1 text-[10px] uppercase tracking-[0.14em] text-slate-500">{node.label}</p> : null}
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="h-8 w-full"
        role="img"
        aria-label={node.label ?? "sparkline"}
      >
        <polyline points={points} fill="none" stroke="currentColor" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}

function formatDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  const hh = String(hours).padStart(2, "0");
  const mm = String(minutes).padStart(2, "0");
  const ss = String(remainder).padStart(2, "0");
  return days > 0 ? `${days}d ${hh}:${mm}:${ss}` : `${hh}:${mm}:${ss}`;
}

export function TimerPrimitive({ node, state, compact }: PrimitiveProps<TimerNode>) {
  const target = resolvePath(state, node.target_path);
  const targetMs = typeof target === "string" || typeof target === "number" ? new Date(target).getTime() : NaN;
  const label = node.label_path ? resolvePath(state, node.label_path) : undefined;

  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!Number.isFinite(targetMs)) {
      return;
    }
    // Renderer-LOCAL ticking per RUNTIME.md: no backend polling for visual-only state.
    const tick = () => {
      if (document.visibilityState !== "hidden") {
        setNow(Date.now());
      }
    };
    tick();
    const interval = window.setInterval(tick, 1000);
    return () => window.clearInterval(interval);
  }, [targetMs]);

  if (!Number.isFinite(targetMs)) {
    return (
      <p className={`font-mono font-semibold tabular-nums text-slate-500 ${compact ? "text-lg" : "text-2xl"}`}>{EM_DASH}</p>
    );
  }

  const deltaSeconds = node.direction === "down" ? (targetMs - now) / 1000 : (now - targetMs) / 1000;
  const complete = node.direction === "down" && deltaSeconds <= 0;

  return (
    <div>
      {label !== undefined && label !== null && label !== "" ? (
        <p className="mb-0.5 truncate text-[10px] uppercase tracking-[0.14em] text-slate-500">{displayValue(label)}</p>
      ) : null}
      <p
        className={`font-mono font-semibold tabular-nums ${complete ? "text-ok" : "text-accent"} ${
          compact ? "text-lg leading-6" : "text-2xl leading-none"
        }`}
      >
        {formatDuration(Math.abs(deltaSeconds))}
      </p>
    </div>
  );
}

export function EmptyStatePrimitive({ node, state }: PrimitiveProps<EmptyStateNode>) {
  const value = resolvePath(state, node.show_if_empty_path);
  const isEmpty =
    value === undefined ||
    value === null ||
    value === "" ||
    (Array.isArray(value) && value.length === 0) ||
    (typeof value === "object" && !Array.isArray(value) && Object.keys(value as object).length === 0);

  if (!isEmpty) {
    return null;
  }

  return (
    <p className="py-3 text-center text-xs text-slate-500">{node.message}</p>
  );
}

// Re-exported so the renderer can share a single visibility gate helper.
export { evaluateShowIf };
