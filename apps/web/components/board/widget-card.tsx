"use client";

import type { PointerEvent as ReactPointerEvent } from "react";

import { WidgetRenderer } from "@/components/board/renderers";
import { WidgetSettingsPanel } from "@/components/board/widget-settings-panel";
import type { JsonObject, WidgetInstance, WidgetManifest, WidgetPlugin } from "@/lib/types";
import { formatFreshness } from "@/lib/utils";

interface WidgetCardProps {
  widget: WidgetInstance;
  manifest: WidgetManifest;
  configSchema: JsonObject;
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

function lifecycleBadgeStyles(state: WidgetInstance["lifecycle_state"]) {
  if (state === "running" || state === "created") {
    return "border-emerald-300/20 bg-emerald-300/12 text-emerald-50";
  }
  if (state === "installing") {
    return "border-cyan-300/20 bg-cyan-300/12 text-cyan-50";
  }
  if (state === "error") {
    return "border-rose-300/20 bg-rose-300/12 text-rose-50";
  }
  if (state === "paused") {
    return "border-amber-300/20 bg-amber-300/12 text-amber-50";
  }
  return "border-white/10 bg-white/5 text-slate-200";
}

function signalDotStyles(state: WidgetInstance["lifecycle_state"]) {
  if (state === "running" || state === "created") {
    return "bg-emerald-300 shadow-[0_0_18px_rgba(74,222,128,0.55)]";
  }
  if (state === "installing") {
    return "bg-cyan-300 shadow-[0_0_18px_rgba(34,211,238,0.55)]";
  }
  if (state === "error") {
    return "bg-rose-300 shadow-[0_0_18px_rgba(251,113,133,0.55)]";
  }
  if (state === "paused") {
    return "bg-amber-300 shadow-[0_0_18px_rgba(252,211,77,0.55)]";
  }
  return "bg-slate-500";
}

export function WidgetCard({
  widget,
  manifest,
  configSchema,
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
  const meta = typeof widget.state.meta === "object" && widget.state.meta ? (widget.state.meta as JsonObject) : {};
  const providerStates = Array.isArray(meta.providers)
    ? (meta.providers as Array<{
        provider_id?: string;
        label?: string;
        status?: string;
        error?: string | null;
      }>)
    : [];
  const primaryProvider =
    typeof meta.primary_provider === "string" ? meta.primary_provider : providerStates[0]?.provider_id;
  const issues = [plugin?.last_error, widget.last_error].filter((value): value is string => Boolean(value));
  const containerClasses = [
    "premium-ring relative flex h-full flex-col overflow-hidden rounded-[30px] border p-4 transition duration-300 md:p-5",
    ghost ? "border-cyan-300/40 bg-[rgba(8,14,26,0.82)] opacity-90" : "bg-[rgba(8,14,26,0.94)]",
    selected
      ? "border-cyan-300/45 shadow-[0_24px_80px_rgba(8,145,178,0.2)]"
      : hovered
        ? "border-white/20 bg-[rgba(10,18,34,0.98)]"
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
      <div className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-[radial-gradient(circle_at_top,rgba(103,232,249,0.1),transparent_65%)] opacity-80" />

      <div className="relative mb-4 flex items-start justify-between gap-3">
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
          <h2 className="mt-2 truncate text-lg font-semibold tracking-tight text-white md:text-[1.15rem]">
            {widget.title}
          </h2>
          <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-400">{manifest.description}</p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs uppercase tracking-[0.16em] ${lifecycleBadgeStyles(widget.lifecycle_state)}`}
          >
            <span className={`h-2 w-2 rounded-full ${signalDotStyles(widget.lifecycle_state)}`} />
            {widget.lifecycle_state}
          </span>
          <button
            type="button"
            onPointerDown={onDragHandlePointerDown}
            className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-100 transition duration-200 hover:-translate-y-0.5 hover:bg-white/10"
          >
            Move
          </button>
        </div>
      </div>

      <div className="relative mb-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <MetricPill label="Freshness" value={formatFreshness(widget.freshness_at)} />
        <MetricPill label="Refresh" value={manifest.refresh_policy.mode} />
        <MetricPill label="Uptime" value={formatUptime(widget.service_uptime_seconds)} />
        <MetricPill label="Restarts" value={String(widget.restart_count)} />
      </div>

      {primaryProvider ? (
        <div className="relative mb-4 rounded-[22px] border border-white/10 bg-black/20 px-3 py-2.5 text-xs text-slate-300">
          <span className="text-slate-500">Primary source</span>
          <span className="ml-2 font-medium text-white">{primaryProvider}</span>
        </div>
      ) : null}

      <div className="relative mb-4 flex flex-wrap gap-2">
        {manifest.allowed_sizes.map((size) => (
          <button
            key={size}
            type="button"
            onMouseEnter={() => onPreviewResize(size)}
            onFocus={() => onPreviewResize(size)}
            onMouseLeave={() => onPreviewResize(null)}
            onBlur={() => onPreviewResize(null)}
            onClick={() => onResize(size)}
            className={`rounded-full px-3 py-1.5 text-xs transition duration-200 ${
              widget.size === size
                ? "border border-cyan-300/30 bg-cyan-300/15 text-cyan-50 shadow-[0_0_0_1px_rgba(103,232,249,0.12)]"
                : "border border-white/10 bg-white/5 text-slate-300 hover:-translate-y-0.5 hover:bg-white/10"
            }`}
          >
            {size}
          </button>
        ))}
      </div>

      {issues.length > 0 ? (
        <div className="relative mb-4 rounded-[24px] border border-rose-300/20 bg-rose-300/10 p-3">
          <p className="text-[11px] uppercase tracking-[0.2em] text-rose-100/80">Runtime alert</p>
          <div className="mt-2 space-y-2">
            {issues.map((issue) => (
              <p key={issue} className="text-xs leading-5 text-rose-50">
                {issue}
              </p>
            ))}
          </div>
        </div>
      ) : null}

      {plugin && !plugin.enabled ? (
        <div className="relative mb-4 rounded-[24px] border border-amber-300/20 bg-amber-300/10 p-3">
          <p className="text-[11px] uppercase tracking-[0.2em] text-amber-100/80">Plugin disabled</p>
          <p className="mt-2 text-xs leading-5 text-amber-50">
            This widget is installed but currently disabled in the plugin layer, so runtime behavior may be limited.
          </p>
        </div>
      ) : null}

      <div className="relative min-h-0 flex-1 overflow-hidden rounded-[24px] border border-white/8 bg-black/20">
        {widget.lifecycle_state === "installing" ? (
          <div className="shimmer absolute inset-0 z-10 bg-[linear-gradient(180deg,rgba(6,10,19,0.38),rgba(6,10,19,0.18))]" />
        ) : null}
        <div className="h-full p-3">
          <WidgetRenderer widget={widget} manifest={manifest} onUpdateConfig={onUpdateConfig} />
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/10 pt-4">
        <button
          type="button"
          onClick={onRefresh}
          className="rounded-full border border-white/10 px-3 py-2 text-xs text-slate-100 transition duration-200 hover:-translate-y-0.5 hover:bg-white/10"
        >
          Refresh
        </button>
        <button
          type="button"
          onClick={onToggleRun}
          className="rounded-full border border-white/10 px-3 py-2 text-xs text-slate-100 transition duration-200 hover:-translate-y-0.5 hover:bg-white/10"
        >
          {isRunning ? "Pause" : "Start"}
        </button>
        <button
          type="button"
          onClick={onRemove}
          className="rounded-full border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs text-rose-100 transition duration-200 hover:-translate-y-0.5 hover:bg-rose-400/20"
        >
          Remove
        </button>
      </div>
      {widget.status_message ? <p className="mt-3 text-xs leading-5 text-slate-400">{widget.status_message}</p> : null}
      <WidgetSettingsPanel
        configSchema={configSchema}
        value={widget.config}
        onSave={onUpdateConfig}
        providerStates={providerStates}
      />
    </div>
  );
}

function MetricPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[22px] border border-white/10 bg-black/20 px-3 py-2.5">
      <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">{label}</p>
      <p className="mt-1 text-sm font-medium text-white">{value}</p>
    </div>
  );
}
