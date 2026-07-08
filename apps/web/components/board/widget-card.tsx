"use client";

import { useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";

import { WidgetRenderer } from "@/components/board/renderers";
import type { BoardDensityDefinition, WidgetAlert } from "@/lib/board-view-settings";
import { getWidgetProviderStates } from "@/lib/board-view-settings";
import { getWidgetDisplayTier, isCompactWidget, isSmallWidget } from "@/lib/widget-display";
import type { JsonObject, WidgetInstance, WidgetManifest } from "@/lib/types";
import { formatFreshness } from "@/lib/utils";

interface WidgetCardProps {
  widget: WidgetInstance;
  manifest: WidgetManifest;
  alert: WidgetAlert;
  canRefresh: boolean;
  densityTone: BoardDensityDefinition["cardTone"];
  selected: boolean;
  hovered: boolean;
  editMode: boolean;
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
  alert,
  canRefresh,
  densityTone,
  selected,
  hovered,
  editMode,
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
  const providerStates = getWidgetProviderStates(widget);
  const primaryProvider =
    typeof meta.primary_provider === "string" ? meta.primary_provider : providerStates[0]?.provider_id;
  const showControls = editMode && !ghost && (selected || hovered);
  const freshness = formatFreshness(widget.freshness_at);
  const uptime = formatUptime(widget.service_uptime_seconds);
  const mode = manifest.refresh_policy.mode;
  const densityCompact = densityTone === "condensed";
  const densityBroadcast = densityTone === "broadcast";
  const paddingClass = compact || densityCompact ? "p-3" : densityBroadcast ? "p-5" : "p-4";
  const titleClass =
    tier === "compact"
      ? "text-[13px] leading-5"
      : small
        ? densityBroadcast
          ? "text-lg leading-6"
          : "text-base leading-6"
        : tier === "expanded"
          ? densityBroadcast
            ? "text-2xl leading-8"
            : "text-xl leading-7"
          : densityBroadcast
            ? "text-xl leading-7"
            : "text-lg leading-6";

  return (
    <div
      className={[
        "group relative flex h-full min-h-0 flex-col overflow-hidden rounded-tile border bg-surface transition-[border-color,background-color] duration-150",
        paddingClass,
        alertFrameClass(alert.level),
        ghost
          ? "border-edge-strong bg-surface-raised shadow-[0_18px_50px_rgba(2,6,23,0.45)]"
          : selected
            ? "border-cyan-300/35 shadow-[0_0_0_1px_rgba(103,232,249,0.08)]"
            : hovered
              ? "border-edge-strong bg-surface-raised"
              : "border-edge",
      ].join(" ")}
      onMouseEnter={() => onHoverChange(true)}
      onMouseLeave={() => {
        onHoverChange(false);
      }}
      onClick={onSelect}
    >
      {alert.level !== "nominal" ? <div className={`absolute inset-x-0 top-0 h-1 ${alertBandClass(alert.level)}`} /> : null}

      {editMode && !ghost ? (
        <>
          <div
            className="absolute inset-x-10 top-0 z-10 h-[10%] min-h-8 max-h-12 cursor-grab border-t border-cyan-200/35 bg-cyan-200/[0.035] opacity-90 active:cursor-grabbing"
            onPointerDown={(event) => {
              event.stopPropagation();
              onDragHandlePointerDown(event);
            }}
          >
            <span className="pointer-events-none absolute left-1/2 top-2 h-1 w-12 -translate-x-1/2 border-y border-cyan-100/35" />
          </div>
          <div
            className="absolute bottom-0 right-0 z-30 h-12 w-12 cursor-nwse-resize bg-gradient-to-tl from-cyan-300/12 via-cyan-300/[0.025] to-transparent"
            aria-label="Resize widget"
            title="Resize"
            onPointerDown={(event) => {
              event.stopPropagation();
              onResizeHandlePointerDown(event);
            }}
          >
            <span className="absolute bottom-2 right-2 h-5 w-5 border-b-2 border-r-2 border-cyan-100/70 group-hover:border-cyan-50" />
          </div>
        </>
      ) : null}

      {editMode && !ghost ? (
        <div
          className={`pointer-events-none absolute right-3 top-3 z-30 flex items-center gap-1 transition-opacity duration-150 ${
            showControls ? "opacity-100" : "opacity-0 group-focus-within:opacity-100"
          }`}
        >
          {canRefresh ? (
            <IconButton label="Refresh" onClick={onRefresh}>
              <RefreshIcon />
            </IconButton>
          ) : null}
          <IconButton label={isRunning ? "Pause" : "Start"} onClick={onToggleRun}>
            {isRunning ? <PauseIcon /> : <PlayIcon />}
          </IconButton>
          <IconButton label="Remove" tone="danger" onClick={onRemove}>
            <CloseIcon />
          </IconButton>
        </div>
      ) : null}

      <div className={`flex min-h-0 flex-1 flex-col ${compact ? "gap-2" : "gap-3"}`}>
        <header className={`flex min-w-0 items-start gap-3 ${editMode ? (compact ? "pr-24" : "pr-28") : ""}`}>
          <div className="min-w-0 flex-1">
            {editMode ? (
              <div className="flex min-w-0 items-center gap-2">
                <span className="truncate text-[10px] uppercase tracking-[0.18em] text-slate-500">
                  {compact ? widget.size : manifest.category}
                </span>
                {!compact ? (
                  <span className="rounded-panel border border-edge px-1.5 py-0.5 text-[9px] uppercase tracking-[0.14em] text-slate-400">
                    {widget.size}
                  </span>
                ) : null}
              </div>
            ) : null}

            <div className={`flex min-w-0 items-center gap-2 ${editMode ? "mt-2" : ""}`}>
              <span className={`h-2 w-2 shrink-0 rounded-tile ${lifecycleTone(widget.lifecycle_state)}`} />
              <h2 className={`truncate font-semibold tracking-tight text-white ${titleClass}`}>{widget.title}</h2>
            </div>
          </div>

          {alert.level !== "nominal" ? <AlertCallout alert={alert} compact={compact || densityCompact} /> : null}
        </header>

        {showStats ? (
          <p className="truncate text-[11px] text-slate-500">
            {freshness} · up {uptime} · {mode} · {widget.restart_count} restarts
            {primaryProvider ? ` · via ${primaryProvider}` : ""}
          </p>
        ) : null}

        <div className="relative min-h-0 flex-1 overflow-hidden">
          <WidgetRenderer widget={widget} manifest={manifest} onUpdateConfig={onUpdateConfig} />
        </div>

        {widget.status_message && !compact ? <p className="text-xs leading-5 text-slate-400">{widget.status_message}</p> : null}
      </div>

    </div>
  );
}

function alertFrameClass(level: WidgetAlert["level"]) {
  if (level === "critical") {
    return "shadow-[inset_0_0_0_1px_rgba(251,113,133,0.28)]";
  }
  if (level === "alert") {
    return "shadow-[inset_0_0_0_1px_rgba(251,191,36,0.22)]";
  }
  if (level === "completed") {
    return "shadow-[inset_0_0_0_1px_rgba(110,231,183,0.2)]";
  }
  return "";
}

function alertBandClass(level: WidgetAlert["level"]) {
  if (level === "critical") {
    return "bg-rose-300";
  }
  if (level === "alert") {
    return "bg-amber-300";
  }
  return "bg-emerald-300";
}

function AlertCallout({ alert, compact }: { alert: WidgetAlert; compact: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const tone =
    alert.level === "critical"
      ? "border-rose-300/25 bg-rose-300/10 text-rose-50"
      : alert.level === "alert"
        ? "border-amber-300/25 bg-amber-300/10 text-amber-50"
        : "border-emerald-300/25 bg-emerald-300/10 text-emerald-50";
  const iconTone =
    alert.level === "critical"
      ? "bg-rose-300 text-rose-950"
      : alert.level === "alert"
        ? "bg-amber-300 text-amber-950"
        : "bg-emerald-300 text-emerald-950";

  return (
    <button
      type="button"
      aria-expanded={expanded}
      aria-label={`${alert.level} alert details`}
      title={expanded ? "Hide alert details" : "Show alert details"}
      onClick={(event) => {
        event.stopPropagation();
        setExpanded((current) => !current);
      }}
      className={[
        "shrink-0 rounded-panel border px-2 py-1.5 text-left transition-colors hover:bg-white/[0.07]",
        compact ? "max-w-44" : "max-w-64",
        tone,
      ].join(" ")}
    >
      <span className="flex items-center justify-end gap-2">
        <span className="text-[9px] uppercase tracking-[0.18em]">{alert.level}</span>
        <span className={`flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold leading-none ${iconTone}`}>
          i
        </span>
      </span>
      {expanded ? (
        <span className={`mt-1.5 block text-right ${compact ? "text-[10px] leading-4" : "text-[11px] leading-4"}`}>
          {alert.reasons.join(" / ")}
        </span>
      ) : null}
    </button>
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
        "pointer-events-auto flex h-7 w-7 items-center justify-center rounded-control border transition-colors",
        tone === "danger"
          ? "border-rose-300/18 bg-rose-300/10 text-rose-100 hover:bg-rose-300/16"
          : "border-edge bg-surface-raised text-slate-200 hover:bg-white/[0.08]",
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
