"use client";

import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";

import { WidgetRenderer } from "@/components/board/renderers";
import { WidgetSettingsPanel } from "@/components/board/widget-settings-panel";
import { getWidgetDisplayTier, isCompactWidget, isSmallWidget } from "@/lib/widget-display";
import type { JsonObject, WidgetInstance, WidgetManifest, WidgetPlugin } from "@/lib/types";
import { formatFreshness } from "@/lib/utils";

interface WidgetCardProps {
  widget: WidgetInstance;
  manifest: WidgetManifest;
  configSchema: JsonObject;
  plugin?: WidgetPlugin | null;
  selected: boolean;
  hovered: boolean;
  showStats: boolean;
  ghost?: boolean;
  onSelect: () => void;
  onHoverChange: (hovered: boolean) => void;
  onDragHandlePointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onResizeHandlePointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
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

function lifecycleTone(state: WidgetInstance["lifecycle_state"]) {
  if (state === "running" || state === "created") {
    return "bg-emerald-300";
  }
  if (state === "installing") {
    return "bg-cyan-300";
  }
  if (state === "error") {
    return "bg-rose-300";
  }
  if (state === "paused") {
    return "bg-amber-300";
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
  showStats,
  ghost = false,
  onSelect,
  onHoverChange,
  onDragHandlePointerDown,
  onResizeHandlePointerDown,
  onRefresh,
  onToggleRun,
  onRemove,
  onUpdateConfig,
}: WidgetCardProps) {
  const isRunning = widget.lifecycle_state === "running" || widget.lifecycle_state === "created";
  const compact = isCompactWidget(widget.size);
  const small = isSmallWidget(widget.size);
  const tier = getWidgetDisplayTier(widget.size);
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
  const showControls = selected || hovered || ghost;
  const titleClass =
    tier === "compact"
      ? "text-[13px] leading-5"
      : small
        ? "text-base leading-6"
        : tier === "expanded"
          ? "text-xl leading-7"
          : "text-lg leading-6";

  return (
    <div
      className={[
        "group relative flex h-full min-h-0 flex-col overflow-hidden rounded-none border bg-[#0a0d11] transition-[border-color,background-color,box-shadow,transform] duration-150",
        compact ? "p-3" : "p-4",
        ghost
          ? "border-white/18 bg-[#0d1116] shadow-[0_18px_50px_rgba(2,6,23,0.45)]"
          : selected
            ? "border-cyan-300/35 shadow-[0_0_0_1px_rgba(103,232,249,0.08)]"
            : hovered
              ? "border-white/18 bg-[#0c1015]"
              : "border-white/10",
      ].join(" ")}
      onMouseEnter={() => onHoverChange(true)}
      onMouseLeave={() => {
        onHoverChange(false);
      }}
      onClick={onSelect}
    >
      {!ghost ? (
        <>
          <div
            className="absolute inset-x-10 top-0 z-10 h-[10%] min-h-8 max-h-12 cursor-grab active:cursor-grabbing"
            onPointerDown={(event) => {
              event.stopPropagation();
              onDragHandlePointerDown(event);
            }}
          />
          <div
            className="absolute bottom-0 right-0 z-30 h-10 w-10 cursor-nwse-resize"
            aria-label="Resize widget"
            title="Resize"
            onPointerDown={(event) => {
              event.stopPropagation();
              onResizeHandlePointerDown(event);
            }}
          >
            <span className="absolute bottom-2 right-2 h-4 w-4 border-b-2 border-r-2 border-white/28 transition group-hover:border-cyan-200/80" />
          </div>
        </>
      ) : null}

      <div
        className={`pointer-events-none absolute right-3 top-3 z-30 flex items-center gap-1 transition-opacity duration-150 ${
          showControls ? "opacity-100" : "opacity-0 group-focus-within:opacity-100"
        }`}
      >
        <IconButton label="Refresh" onClick={onRefresh}>
          <RefreshIcon />
        </IconButton>
        <IconButton label={isRunning ? "Pause" : "Start"} onClick={onToggleRun}>
          {isRunning ? <PauseIcon /> : <PlayIcon />}
        </IconButton>
        <IconButton label="Remove" tone="danger" onClick={onRemove}>
          <CloseIcon />
        </IconButton>
      </div>

      {showStats ? (
        <WidgetStatsOverlay
          compact={compact}
          freshness={formatFreshness(widget.freshness_at)}
          uptime={formatUptime(widget.service_uptime_seconds)}
          mode={manifest.refresh_policy.mode}
          restarts={String(widget.restart_count)}
        />
      ) : null}

      <div className={`flex min-h-0 flex-1 flex-col ${compact ? "gap-2" : "gap-3"}`}>
        <header className={`min-w-0 ${compact ? "pr-24" : "pr-28"}`}>
          <div className="flex min-w-0 items-center gap-2">
            <span className={`h-2 w-2 shrink-0 rounded-none ${lifecycleTone(widget.lifecycle_state)}`} />
            <span className="truncate text-[10px] uppercase tracking-[0.18em] text-slate-500">
              {compact ? widget.size : manifest.category}
            </span>
            {!compact ? (
              <span className="rounded border border-white/10 px-1.5 py-0.5 text-[9px] uppercase tracking-[0.14em] text-slate-400">
                {widget.size}
              </span>
            ) : null}
          </div>

          <h2 className={`mt-2 truncate font-semibold tracking-tight text-white ${titleClass}`}>{widget.title}</h2>

          {compact ? (
            <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-400">
              <span className="truncate">{formatFreshness(widget.freshness_at)}</span>
              <span className="text-slate-600">/</span>
              <span className="truncate">{manifest.refresh_policy.mode}</span>
            </div>
          ) : (
            <p className="mt-1 line-clamp-1 text-xs text-slate-400">{manifest.description}</p>
          )}
        </header>

        {issues.length > 0 ? (
          <div className={`rounded-[14px] border border-rose-300/18 bg-rose-300/8 ${compact ? "px-2.5 py-2" : "px-3 py-2.5"}`}>
            <p className="text-[10px] uppercase tracking-[0.18em] text-rose-100/80">Runtime issue</p>
            <p className={`mt-1 text-rose-50 ${compact ? "line-clamp-2 text-[11px] leading-4" : "line-clamp-2 text-xs leading-5"}`}>
              {issues[0]}
            </p>
          </div>
        ) : null}

        {primaryProvider && !compact ? (
          <div className="rounded-[14px] border border-white/10 bg-black/20 px-3 py-2 text-[11px] text-slate-300">
            <span className="text-slate-500">Source</span>
            <span className="ml-2 text-white">{primaryProvider}</span>
          </div>
        ) : null}

          <div className="relative min-h-0 flex-1 overflow-hidden rounded-none border border-white/8 bg-[#05070a]">
          <div className={`h-full ${compact ? "p-2.5" : "p-3"}`}>
            <WidgetRenderer widget={widget} manifest={manifest} onUpdateConfig={onUpdateConfig} />
          </div>

        </div>

        {widget.status_message && !compact ? <p className="text-xs leading-5 text-slate-400">{widget.status_message}</p> : null}
      </div>

      {!compact && selected ? (
        <WidgetSettingsPanel
          configSchema={configSchema}
          value={widget.config}
          onSave={onUpdateConfig}
          providerStates={providerStates}
        />
      ) : null}
    </div>
  );
}

function WidgetStatsOverlay({
  compact,
  freshness,
  uptime,
  mode,
  restarts,
}: {
  compact: boolean;
  freshness: string;
  uptime: string;
  mode: string;
  restarts: string;
}) {
  return (
    <div
      className={`pointer-events-none absolute inset-x-3 z-20 grid gap-1.5 rounded-none border border-cyan-200/18 bg-[#05070a]/88 p-2 shadow-[0_16px_40px_rgba(2,6,23,0.38)] backdrop-blur ${
        compact ? "top-9 grid-cols-2" : "top-12 grid-cols-2 xl:grid-cols-4"
      }`}
    >
      <MetricPill compact={compact} label="Fresh" value={freshness} />
      <MetricPill compact={compact} label="Uptime" value={uptime} />
      <MetricPill compact={compact} label="Mode" value={mode} />
      <MetricPill compact={compact} label="Restarts" value={restarts} />
    </div>
  );
}

function MetricPill({ label, value, compact }: { label: string; value: string; compact: boolean }) {
  return (
    <div className={`rounded-none border border-white/10 bg-black/24 ${compact ? "px-2 py-1" : "px-3 py-2"}`}>
      <p className={`${compact ? "text-[8px]" : "text-[10px]"} uppercase tracking-[0.16em] text-slate-500`}>{label}</p>
      <p className={`mt-1 truncate font-medium text-white ${compact ? "text-[10px]" : "text-sm"}`}>{value}</p>
    </div>
  );
}

function IconButton({
  label,
  tone = "default",
  onClick,
  onPointerDown,
  children,
}: {
  label: string;
  tone?: "default" | "danger";
  onClick?: () => void;
  onPointerDown?: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={(event) => {
        event.stopPropagation();
        onClick?.();
      }}
      onPointerDown={(event) => {
        event.stopPropagation();
        onPointerDown?.(event);
      }}
      className={[
        "pointer-events-auto flex h-7 w-7 items-center justify-center rounded border transition-colors",
        tone === "danger"
          ? "border-rose-300/18 bg-rose-300/10 text-rose-100 hover:bg-rose-300/16"
          : "border-white/10 bg-[#0c1015] text-slate-200 hover:bg-[#121821]",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

function IconFrame({ children }: { children: ReactNode }) {
  return <span className="flex h-3.5 w-3.5 items-center justify-center">{children}</span>;
}

function RefreshIcon() {
  return (
    <IconFrame>
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 fill-none stroke-current" strokeWidth="1.5">
        <path d="M13 4.5V1.8m0 2.7h-2.7" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M13 4.2A5.4 5.4 0 1 0 13.2 11" strokeLinecap="round" />
      </svg>
    </IconFrame>
  );
}

function PauseIcon() {
  return (
    <IconFrame>
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 fill-current">
        <rect x="4" y="3.2" width="2.3" height="9.6" rx="0.8" />
        <rect x="9.7" y="3.2" width="2.3" height="9.6" rx="0.8" />
      </svg>
    </IconFrame>
  );
}

function PlayIcon() {
  return (
    <IconFrame>
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 fill-current">
        <path d="M5 3.2v9.6l7-4.8-7-4.8Z" />
      </svg>
    </IconFrame>
  );
}

function CloseIcon() {
  return (
    <IconFrame>
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 fill-none stroke-current" strokeWidth="1.6">
        <path d="M4.2 4.2 11.8 11.8M11.8 4.2 4.2 11.8" strokeLinecap="round" />
      </svg>
    </IconFrame>
  );
}
