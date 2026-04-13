"use client";

import type { JsonObject, WidgetInstance, WidgetManifest } from "@/lib/types";
import { formatFreshness } from "@/lib/utils";
import { WidgetRenderer } from "@/components/board/renderers";

interface WidgetCardProps {
  widget: WidgetInstance;
  manifest: WidgetManifest;
  onResize: (size: WidgetInstance["size"]) => void;
  onRefresh: () => void;
  onToggleRun: () => void;
  onRemove: () => void;
  onUpdateConfig: (config: JsonObject) => void | Promise<void>;
}

export function WidgetCard({
  widget,
  manifest,
  onResize,
  onRefresh,
  onToggleRun,
  onRemove,
  onUpdateConfig,
}: WidgetCardProps) {
  const isRunning = widget.lifecycle_state === "running" || widget.lifecycle_state === "created";
  return (
    <div className="flex h-full flex-col rounded-[28px] border border-white/10 bg-[rgba(8,14,26,0.92)] p-4 shadow-[0_24px_80px_rgba(2,8,23,0.32)]">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{manifest.category}</p>
          <h2 className="mt-1 text-lg font-semibold text-white">{widget.title}</h2>
        </div>
        <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300">
          {widget.lifecycle_state}
        </span>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <span>Freshness {formatFreshness(widget.freshness_at)}</span>
        <span className="text-slate-600">•</span>
        <span>{manifest.refresh_policy.mode}</span>
        <span className="text-slate-600">•</span>
        <span>Preferred {manifest.preferred_size}</span>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        <WidgetRenderer widget={widget} manifest={manifest} onUpdateConfig={onUpdateConfig} />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/10 pt-4">
        <select
          value={widget.size}
          onChange={(event) => onResize(event.target.value as WidgetInstance["size"])}
          className="rounded-full border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-200 outline-none"
        >
          {manifest.allowed_sizes.map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
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
      {widget.last_error ? <p className="mt-3 text-xs text-rose-300">{widget.last_error}</p> : null}
    </div>
  );
}
