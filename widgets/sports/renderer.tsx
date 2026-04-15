"use client";

import { getWidgetDisplayTier } from "@/lib/widget-display";
import type { WidgetRendererProps } from "@/lib/types";

export function SportsRenderer({ widget, onUpdateConfig }: WidgetRendererProps) {
  const entries = Array.isArray(widget.state.entries)
    ? (widget.state.entries as Array<{ label: string; detail: string }>)
    : [];
  const activeSport = String(widget.state.sport ?? widget.config.sport ?? "ipl");
  const headline = typeof widget.state.headline === "string" ? widget.state.headline : widget.title;
  const status = typeof widget.state.status === "string" ? widget.state.status : "Live";
  const tier = getWidgetDisplayTier(widget.size);
  const compact = tier === "compact";
  const visibleEntries = entries.slice(0, compact ? 2 : tier === "expanded" ? 6 : 3);

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-[0.18em] text-emerald-300/70">Sports</p>
          <h3 className={`mt-1 truncate font-semibold text-white ${compact ? "text-sm" : "text-base"}`}>{headline}</h3>
        </div>
        <span className="rounded border border-emerald-300/18 bg-emerald-300/10 px-2 py-1 text-[10px] uppercase tracking-[0.12em] text-emerald-100">
          {status}
        </span>
      </div>

      {!compact ? (
        <div className="flex flex-wrap gap-2">
          {["ipl", "f1", "football"].map((sport) => (
            <button
              key={sport}
              type="button"
              onClick={() => void onUpdateConfig?.({ ...widget.config, sport })}
              className={`rounded-[10px] border px-2.5 py-1 text-[11px] transition ${
                activeSport === sport
                  ? "border-emerald-300/22 bg-emerald-300/14 text-emerald-50"
                  : "border-white/10 bg-white/[0.04] text-slate-300 hover:bg-white/[0.08]"
              }`}
            >
              {sport.toUpperCase()}
            </button>
          ))}
        </div>
      ) : (
        <div className="rounded-[14px] border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-slate-300">
          {activeSport.toUpperCase()}
        </div>
      )}

      <div className={`grid gap-2 ${compact ? "grid-cols-1" : tier === "expanded" ? "grid-cols-2" : "grid-cols-1"}`}>
        {visibleEntries.map((entry, index) => (
          <div key={`${entry.label}-${index}`} className="rounded-[14px] border border-white/10 bg-white/[0.04] p-3">
            <p className={`font-medium text-white ${compact ? "text-xs leading-5" : "text-sm"}`}>{entry.label}</p>
            <p className="mt-1 text-xs leading-5 text-slate-400">{entry.detail}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
