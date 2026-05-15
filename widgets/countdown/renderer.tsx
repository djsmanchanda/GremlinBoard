"use client";

import { useEffect, useMemo, useState } from "react";

import { getWidgetDisplayTier } from "@/lib/widget-display";
import type { JsonObject, JsonValue, WidgetRendererProps } from "@/lib/types";

interface CountdownTimer {
  id: string;
  label: string;
  target_time: string;
  duration_seconds?: number;
}

const MAX_TIMERS = 4;
const QUICK_DURATIONS = [
  { label: "15m", seconds: 15 * 60 },
  { label: "1h", seconds: 60 * 60 },
  { label: "1d", seconds: 24 * 60 * 60 },
];

function timerId() {
  return `timer-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function isObject(value: JsonValue | undefined): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toTimer(value: JsonValue | undefined, index: number): CountdownTimer | null {
  if (!isObject(value) || typeof value.target_time !== "string") {
    return null;
  }
  const label = typeof value.label === "string" && value.label.trim() ? value.label : `Timer ${index + 1}`;
  const duration = typeof value.duration_seconds === "number" && value.duration_seconds > 0 ? value.duration_seconds : undefined;
  return {
    id: typeof value.id === "string" && value.id.trim() ? value.id : `${label}-${index}`,
    label,
    target_time: value.target_time,
    duration_seconds: duration,
  };
}

function timersFromConfig(config: JsonObject, state: JsonObject, title: string) {
  const configTimers = Array.isArray(config.timers)
    ? config.timers.map((timer, index) => toTimer(timer, index)).filter((timer): timer is CountdownTimer => Boolean(timer))
    : [];
  if (configTimers.length > 0) {
    return configTimers.slice(0, MAX_TIMERS);
  }

  const stateTimers = Array.isArray(state.timers)
    ? state.timers.map((timer, index) => toTimer(timer, index)).filter((timer): timer is CountdownTimer => Boolean(timer))
    : [];
  if (stateTimers.length > 0) {
    return stateTimers.slice(0, MAX_TIMERS);
  }

  const targetTime = typeof config.target_time === "string" ? config.target_time : typeof state.target_time === "string" ? state.target_time : "";
  if (!targetTime) {
    return [];
  }
  return [
    {
      id: "primary",
      label: typeof config.label === "string" ? config.label : typeof state.label === "string" ? state.label : title,
      target_time: targetTime,
    },
  ];
}

function toDatetimeLocalValue(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function fromDatetimeLocalValue(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString();
}

function targetFromDuration(seconds: number) {
  return new Date(Date.now() + seconds * 1000).toISOString();
}

function remainingSeconds(targetTime: string, now: number) {
  const target = new Date(targetTime).getTime();
  if (!Number.isFinite(target)) {
    return 0;
  }
  return Math.max(Math.floor((target - now) / 1000), 0);
}

function formatRemaining(seconds: number, compact: boolean) {
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  if (days > 0) {
    return compact ? `${days}d ${hours}h` : `${days}d ${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
  }
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function durationFromNow(targetTime: string) {
  return Math.max(Math.floor((new Date(targetTime).getTime() - Date.now()) / 1000), 1);
}

export function CountdownRenderer({ widget, onUpdateConfig }: WidgetRendererProps) {
  const tier = getWidgetDisplayTier(widget.size);
  const compact = tier === "compact";
  const expanded = tier === "expanded";
  const [now, setNow] = useState(() => Date.now());
  const [draftLabel, setDraftLabel] = useState("");
  const [draftTarget, setDraftTarget] = useState(() => toDatetimeLocalValue(targetFromDuration(60 * 60)));
  const timers = useMemo(() => timersFromConfig(widget.config, widget.state, widget.title), [widget.config, widget.state, widget.title]);
  const visibleTimers = compact ? timers.slice(0, 1) : timers;
  const canAdd = timers.length < MAX_TIMERS;

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, []);

  function commitTimers(nextTimers: CountdownTimer[]) {
    const { label: _legacyLabel, target_time: _legacyTargetTime, ...nextConfig } = widget.config;
    void onUpdateConfig?.({
      ...nextConfig,
      timers: nextTimers.slice(0, MAX_TIMERS).map((timer) => ({
        id: timer.id,
        label: timer.label,
        target_time: timer.target_time,
        duration_seconds: timer.duration_seconds ?? durationFromNow(timer.target_time),
      })),
    });
  }

  function addTimer(seconds?: number) {
    if (!canAdd) {
      return;
    }
    const targetTime = seconds ? targetFromDuration(seconds) : fromDatetimeLocalValue(draftTarget);
    if (!targetTime) {
      return;
    }
    commitTimers([
      ...timers,
      {
        id: timerId(),
        label: draftLabel.trim() || `Timer ${timers.length + 1}`,
        target_time: targetTime,
        duration_seconds: seconds ?? durationFromNow(targetTime),
      },
    ]);
    setDraftLabel("");
  }

  function removeTimer(timerIdToRemove: string) {
    commitTimers(timers.filter((timer) => timer.id !== timerIdToRemove));
  }

  function restartTimer(timer: CountdownTimer) {
    commitTimers(
      timers.map((item) =>
        item.id === timer.id
          ? {
              ...item,
              target_time: targetFromDuration(item.duration_seconds ?? durationFromNow(item.target_time)),
            }
          : item,
      ),
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="min-h-0 flex-1 space-y-2 overflow-hidden">
        {visibleTimers.length === 0 ? (
          <div className="flex h-full items-center justify-center border border-dashed border-white/12 bg-white/[0.03] p-3 text-center text-xs text-slate-400">
            Add up to four countdowns.
          </div>
        ) : (
          visibleTimers.map((timer) => {
            const remaining = remainingSeconds(timer.target_time, now);
            const complete = remaining === 0;
            return (
              <div
                key={timer.id}
                className={`group/timer border bg-cyan-400/10 ${complete ? "border-amber-300/24" : "border-cyan-400/18"} ${
                  compact ? "p-2" : "p-2.5"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-[11px] font-medium text-slate-100">{timer.label}</p>
                    {!compact ? (
                      <p className="mt-0.5 truncate text-[10px] uppercase tracking-[0.12em] text-slate-500">
                        {complete ? "Complete" : new Date(timer.target_time).toLocaleString()}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    {complete && !compact ? (
                      <button
                        type="button"
                        onClick={() => restartTimer(timer)}
                        className="border border-cyan-300/20 bg-cyan-300/10 px-2 py-1 text-[10px] text-cyan-100 transition hover:bg-cyan-300/18"
                      >
                        Restart
                      </button>
                    ) : null}
                    <button
                      type="button"
                      aria-label={`Remove ${timer.label}`}
                      title="Remove"
                      onClick={() => removeTimer(timer.id)}
                      className="flex h-5 w-5 items-center justify-center border border-white/10 bg-black/20 text-[11px] text-slate-300 transition hover:border-rose-300/25 hover:bg-rose-300/12 hover:text-rose-100"
                    >
                      x
                    </button>
                  </div>
                </div>
                <p
                  className={`mt-2 font-mono font-semibold tracking-[0.12em] ${
                    complete ? "text-amber-100" : "text-cyan-100"
                  } ${compact ? "text-lg leading-6" : expanded ? "text-3xl leading-none" : "text-2xl leading-none"}`}
                >
                  {formatRemaining(remaining, compact)}
                </p>
              </div>
            );
          })
        )}
      </div>

      {!compact ? (
        <div className="shrink-0 border border-white/10 bg-black/16 p-2">
          <div className="flex flex-wrap gap-1.5">
            <input
              value={draftLabel}
              onChange={(event) => setDraftLabel(event.target.value)}
              placeholder="Label"
              disabled={!canAdd}
              className="min-w-[96px] flex-1 border border-white/10 bg-slate-950/70 px-2 py-1.5 text-xs text-slate-100 outline-none placeholder:text-slate-500 focus:border-cyan-300/35 disabled:opacity-45"
            />
            <input
              type="datetime-local"
              value={draftTarget}
              onChange={(event) => setDraftTarget(event.target.value)}
              disabled={!canAdd}
              className="min-w-[142px] flex-1 border border-white/10 bg-slate-950/70 px-2 py-1.5 text-xs text-slate-100 outline-none focus:border-cyan-300/35 disabled:opacity-45"
            />
            <button
              type="button"
              onClick={() => addTimer()}
              disabled={!canAdd}
              className="border border-cyan-300/20 bg-cyan-300/10 px-2.5 py-1.5 text-xs text-cyan-100 transition hover:bg-cyan-300/18 disabled:opacity-45"
            >
              Add
            </button>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {QUICK_DURATIONS.map((duration) => (
              <button
                key={duration.label}
                type="button"
                disabled={!canAdd}
                onClick={() => addTimer(duration.seconds)}
                className="border border-white/10 bg-white/[0.04] px-2 py-1 text-[10px] text-slate-300 transition hover:bg-white/[0.08] disabled:opacity-45"
              >
                +{duration.label}
              </button>
            ))}
            <span className="ml-auto py-1 text-[10px] uppercase tracking-[0.14em] text-slate-500">
              {timers.length}/{MAX_TIMERS}
            </span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
