"use client";

import type { PointerEvent as ReactPointerEvent } from "react";

import type { JsonObject, WidgetInstance, WidgetManifest, WidgetPlugin } from "@/lib/types";
import { formatFreshness } from "@/lib/utils";
import { WidgetRenderer } from "@/components/board/renderers";

interface WidgetCardProps {
  widget: WidgetInstance;
  manifest: WidgetManifest;
  plugin?: WidgetPlugin | null;
  selected: boolean;
  hovered: boolean;
  ghost?: boolean;
  onSelect: () => void;
  onHoverChange: (hovered: boolean) => void;
  onDragHandlePointerDown: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onResize: (size: WidgetInstance["size"]) => void;
  onPreviewResize: (size: WidgetInstance["size"] | null) => void;
  onRefresh: () => void;
  onToggleRun: () => void;
  onRemove: () => void;
  onUpdateConfig: (config: JsonObject) => void | Promise<void>;
}

function formatUptime(seconds: number) {
  if (seconds < 60) {
    return `${seconds}s`;
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m`;
  }
  return `${Math.floor(seconds / 3600)}h`;
}

export function WidgetCard({
  widget,
  manifest,
  plugin,
  selected,
  hovered,
  ghost = false,
  onSelect,
  onHoverChange,
  onDragHandlePointerDown,
  onResize,
  onPreviewResize,
  onRefresh,
  onToggleRun,
  onRemove,
  onUpdateConfig,
}: WidgetCardProps) {
  const isRunning = widget.lifecycle_state === "running" || widget.lifecycle_state === "created";
  const containerClasses = [
    "flex h-full flex-col rounded-[28px] border p-4 shadow-[0_24px_80px_rgba(2,8,23,0.28)] transition duration-300",
    ghost ? "border-cyan-300/40 bg-[rgba(8,14,26,0.82)] opacity-90" : "bg-[rgba(8,14,26,0.94)]",
    selected
      ? "border-cyan-300/45 shadow-[0_24px_80px_rgba(8,145,178,0.18)]"
      : hovered
        ? "border-white/20 bg-[rgba(10,18,34,0.96)]"
        : "border-white/10",
  ].join(" ");

  return (
    <div
      className={containerClasses}
      onMouseEnter={() => onHoverChange(true)}
      onMouseLeave={() => {
        onHoverChange(false);
        onPreviewResize(null);
      }}
      onClick={onSelect}
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{manifest.category}</p>
            <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-slate-400">
              v{plugin?.version ?? manifest.version}
            </span>
            {plugin && !plugin.enabled ? (
              <span className="rounded-full border border-amber-300/20 bg-amber-300/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-amber-100">
                disabled
              </span>
            ) : null}
          </div>
          <h2 className="mt-1 truncate text-lg font-semibold text-white">{widget.title}</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300">
            {widget.lifecycle_state}
          </span>
          <button
            type="button"
            onPointerDown={onDragHandlePointerDown}
            className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-200 transition hover:bg-white/10"
          >
            Move
          </button>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <span>Freshness {formatFreshness(widget.freshness_at)}</span>
        <span className="text-slate-600">•</span>
        <span>{manifest.refresh_policy.mode}</span>
        <span className="text-slate-600">•</span>
        <span>Uptime {formatUptime(widget.service_uptime_seconds)}</span>
        <span className="text-slate-600">•</span>
        <span>Restarts {widget.restart_count}</span>
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        {manifest.allowed_sizes.map((size) => (
          <button
            key={size}
            type="button"
            onMouseEnter={() => onPreviewResize(size)}
            onFocus={() => onPreviewResize(size)}
            onMouseLeave={() => onPreviewResize(null)}
            onBlur={() => onPreviewResize(null)}
            onClick={() => onResize(size)}
            className={`rounded-full px-3 py-1 text-xs transition ${
              widget.size === size
                ? "border border-cyan-300/30 bg-cyan-300/15 text-cyan-50"
                : "border border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
            }`}
          >
            {size}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        <WidgetRenderer widget={widget} manifest={manifest} onUpdateConfig={onUpdateConfig} />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/10 pt-4">
        <button
          type="button"
          onClick={onRefresh}
          className="rounded-full border border-white/10 px-3 py-2 text-xs text-slate-200 transition hover:bg-white/10"
        >
          Refresh
        </button>
        <button
          type="button"
          onClick={onToggleRun}
          className="rounded-full border border-white/10 px-3 py-2 text-xs text-slate-200 transition hover:bg-white/10"
        >
          {isRunning ? "Pause" : "Start"}
        </button>
        <button
          type="button"
          onClick={onRemove}
          className="rounded-full border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs text-rose-100 transition hover:bg-rose-400/20"
        >
          Remove
        </button>
      </div>
      {widget.status_message ? <p className="mt-3 text-xs text-slate-400">{widget.status_message}</p> : null}
      {widget.last_error ? <p className="mt-1 text-xs text-rose-300">{widget.last_error}</p> : null}
    </div>
  );
}
