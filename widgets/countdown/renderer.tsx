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

function targetFromDuration(seconds: number, now = Date.now()) {
  return new Date(now + seconds * 1000).toISOString();
}

function parseDuration(value: string) {
  const normalized = value.trim().toLowerCase();
  if (!normalized) {
    return null;
  }

  const tokenPattern = /(\d+)\s*([dhms])/g;
  let seconds = 0;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = tokenPattern.exec(normalized)) !== null) {
    if (normalized.slice(cursor, match.index).trim()) {
      return null;
    }
    const amount = Number(match[1]);
    const unit = match[2];
    seconds += amount * (unit === "d" ? 86_400 : unit === "h" ? 3600 : unit === "m" ? 60 : 1);
    cursor = tokenPattern.lastIndex;
  }

  return cursor === normalized.length && seconds > 0 ? seconds : null;
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

function durationFromNow(targetTime: string, now = Date.now()) {
  return Math.max(Math.floor((new Date(targetTime).getTime() - now) / 1000), 1);
}

export function CountdownRenderer({ widget, onUpdateConfig }: WidgetRendererProps) {
  const tier = getWidgetDisplayTier(widget.size);
  const compact = tier === "compact";
  const expanded = tier === "expanded";
  const [now, setNow] = useState(() => Date.now());
  const [draftLabel, setDraftLabel] = useState("");
  const [draftTarget, setDraftTarget] = useState(() => toDatetimeLocalValue(targetFromDuration(60 * 60)));
  const [draftDuration, setDraftDuration] = useState("");
  const timers = useMemo(() => timersFromConfig(widget.config, widget.state, widget.title), [widget.config, widget.state, widget.title]);
  const visibleTimers = compact ? timers.slice(0, 1) : timers;
  const canAdd = timers.length < MAX_TIMERS;

  useEffect(() => {
    const hasActiveTimer = timers.some((timer) => remainingSeconds(timer.target_time, Date.now()) > 0);
    if (!hasActiveTimer) {
      return;
    }

    const tick = () => {
      if (document.visibilityState !== "hidden") {
        setNow(Date.now());
      }
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        tick();
      }
    };

    tick();
    const interval = window.setInterval(tick, 1000);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [timers]);

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
    const startedAt = Date.now();
    setNow(startedAt);
    const targetTime = seconds ? targetFromDuration(seconds, startedAt) : fromDatetimeLocalValue(draftTarget);
    if (!targetTime) {
      return;
    }
    commitTimers([
      ...timers,
      {
        id: timerId(),
        label: draftLabel.trim() || `Timer ${timers.length + 1}`,
        target_time: targetTime,
        duration_seconds: seconds ?? durationFromNow(targetTime, startedAt),
      },
    ]);
    setDraftLabel("");
  }

  function addCustomDuration() {
    const seconds = parseDuration(draftDuration);
    if (seconds === null) {
      return;
    }
    addTimer(seconds);
    setDraftDuration("");
  }

  function removeTimer(timerIdToRemove: string) {
    commitTimers(timers.filter((timer) => timer.id !== timerIdToRemove));
  }

  function restartTimer(timer: CountdownTimer) {
    const restartedAt = Date.now();
    setNow(restartedAt);
    commitTimers(
      timers.map((item) =>
        item.id === timer.id
          ? {
              ...item,
              target_time: targetFromDuration(item.duration_seconds ?? durationFromNow(item.target_time, restartedAt), restartedAt),
            }
          : item,
      ),
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="min-h-0 flex-1 divide-y divide-edge overflow-y-auto pr-1">
        {visibleTimers.length === 0 ? (
          <div className="flex h-full items-center justify-center p-3 text-center text-xs text-slate-400">
            Add up to four countdowns.
          </div>
        ) : (
          visibleTimers.map((timer) => {
            const remaining = remainingSeconds(timer.target_time, now);
            const complete = remaining === 0;
            return (
              <div key={timer.id} className={`group/timer ${compact ? "py-2" : "py-2.5"}`}>
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
                        className="rounded-control border border-edge bg-accent/10 px-2 py-1 text-[10px] text-accent transition hover:bg-accent/20"
                      >
                        Restart
                      </button>
                    ) : null}
                    <button
                      type="button"
                      aria-label={`Remove ${timer.label}`}
                      title="Remove"
                      onClick={() => removeTimer(timer.id)}
                      className="flex h-5 w-5 items-center justify-center rounded-control text-[11px] text-slate-400 transition hover:bg-critical/10 hover:text-critical"
                    >
                      x
                    </button>
                  </div>
                </div>
                <p
                  className={`mt-2 font-mono font-semibold tracking-[0.12em] ${
                    complete ? "text-ok" : "text-accent"
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
        <div className="shrink-0 rounded-panel border border-edge bg-surface-inset p-2">
          <div className="flex flex-wrap gap-1.5">
            <input
              value={draftLabel}
              onChange={(event) => setDraftLabel(event.target.value)}
              placeholder="Label"
              disabled={!canAdd}
              className="min-w-[96px] flex-1 rounded-control border border-edge bg-bg px-2 py-1.5 text-xs text-slate-100 outline-none placeholder:text-slate-500 focus:border-accent disabled:opacity-45"
            />
            <input
              type="datetime-local"
              value={draftTarget}
              onChange={(event) => setDraftTarget(event.target.value)}
              disabled={!canAdd}
              className="min-w-[142px] flex-1 rounded-control border border-edge bg-bg px-2 py-1.5 text-xs text-slate-100 outline-none focus:border-accent disabled:opacity-45"
            />
            <button
              type="button"
              onClick={() => addTimer()}
              disabled={!canAdd}
              className="rounded-control border border-edge bg-accent/10 px-2.5 py-1.5 text-xs text-accent transition hover:bg-accent/20 disabled:opacity-45"
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
                className="rounded-control border border-edge bg-surface-raised px-2 py-1 text-[10px] text-slate-300 transition hover:border-edge-strong disabled:opacity-45"
              >
                +{duration.label}
              </button>
            ))}
            <input
              value={draftDuration}
              onChange={(event) => setDraftDuration(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  addCustomDuration();
                }
              }}
              aria-label="Custom countdown duration"
              title="Custom duration, for example 30s, 18m, or 3h 4m"
              placeholder="1m 30s"
              disabled={!canAdd}
              className="w-20 rounded-control border border-edge bg-bg px-2 py-1 text-[10px] text-slate-100 outline-none placeholder:text-slate-600 focus:border-accent disabled:opacity-45"
            />
            <button
              type="button"
              aria-label="Add custom countdown duration"
              title="Add custom duration"
              disabled={!canAdd || parseDuration(draftDuration) === null}
              onClick={addCustomDuration}
              className="rounded-control border border-edge bg-surface-raised px-2 py-1 text-[10px] text-slate-300 transition hover:border-edge-strong disabled:opacity-45"
            >
              +
            </button>
            <span className="ml-auto py-1 text-[10px] uppercase tracking-[0.14em] text-slate-500">
              {timers.length}/{MAX_TIMERS}
            </span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
