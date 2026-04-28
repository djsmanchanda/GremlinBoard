"use client";

import { useEffect, useMemo, useState } from "react";

import { getWidgetDisplayTier } from "@/lib/widget-display";
import type { WidgetRendererProps } from "@/lib/types";

function formatRemaining(targetTime: string, now: number) {
  const target = new Date(targetTime).getTime();
  if (!Number.isFinite(target)) {
    return "--:--:--";
  }

  const remaining = Math.max(Math.floor((target - now) / 1000), 0);
  const hours = Math.floor(remaining / 3600);
  const minutes = Math.floor((remaining % 3600) / 60);
  const seconds = remaining % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function CountdownRenderer({ widget }: WidgetRendererProps) {
  const label = typeof widget.state.label === "string" ? widget.state.label : widget.title;
  const targetTime = typeof widget.state.target_time === "string" ? widget.state.target_time : "";
  const [now, setNow] = useState(() => Date.now());
  const tier = getWidgetDisplayTier(widget.size);
  const compact = tier === "compact";
  const remaining = useMemo(
    () =>
      targetTime
        ? formatRemaining(targetTime, now)
        : typeof widget.state.formatted_remaining === "string"
          ? widget.state.formatted_remaining
          : "--:--:--",
    [now, targetTime, widget.state.formatted_remaining],
  );

  useEffect(() => {
    if (!targetTime || remaining === "00:00:00") {
      return;
    }
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [remaining, targetTime]);

  return (
    <div className="flex h-full flex-col justify-between gap-3">
      <div className="min-w-0">
        <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Countdown</p>
        <h3 className={`mt-1 truncate font-semibold text-white ${compact ? "text-sm" : "text-base"}`}>{label}</h3>
      </div>

      <div className={`rounded-none border border-cyan-400/18 bg-cyan-400/10 ${compact ? "p-2.5" : "p-3"}`}>
        <p
          className={`font-mono font-semibold tracking-[0.16em] text-cyan-100 ${
            compact ? "text-lg leading-6" : tier === "expanded" ? "text-4xl leading-none" : "text-3xl leading-none"
          }`}
        >
          {remaining}
        </p>
        {!compact ? (
          <p className="mt-2 text-xs text-slate-300">Target {targetTime ? new Date(targetTime).toLocaleString() : "-"}</p>
        ) : null}
      </div>
    </div>
  );
}
