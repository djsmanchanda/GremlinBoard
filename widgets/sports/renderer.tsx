"use client";

import { getWidgetDisplayTier } from "@/lib/widget-display";
import type { WidgetRendererProps } from "@/lib/types";

export function SportsRenderer({ widget, onUpdateConfig }: WidgetRendererProps) {
  const entries = Array.isArray(widget.state.entries)
    ? (widget.state.entries as Array<{ label: string; detail: string }>)
    : [];
  const activeSport = String(widget.state.sport ?? widget.config.sport ?? "ipl");
  const tier = getWidgetDisplayTier(widget.size);
  const compact = tier === "compact";
  const visibleEntries = entries.slice(0, compact ? 2 : tier === "expanded" ? 8 : 4);

  return (
    <div className="flex h-full flex-col gap-2">
      {!compact ? (
        <div className="flex flex-wrap gap-2">
          {["ipl", "f1", "football"].map((sport) => (
            <button
              key={sport}
              type="button"
              onClick={() => void onUpdateConfig?.({ ...widget.config, sport })}
              className={`rounded-control border px-2.5 py-1 text-[11px] transition ${
                activeSport === sport
                  ? "border-ok/30 bg-ok/10 text-ok"
                  : "border-edge bg-surface-raised text-slate-300 hover:border-edge-strong"
              }`}
            >
              {sport.toUpperCase()}
            </button>
          ))}
        </div>
      ) : (
        <p className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{activeSport.toUpperCase()}</p>
      )}

      <div className={`grid gap-x-4 ${compact ? "grid-cols-1 divide-y divide-edge" : tier === "expanded" ? "grid-cols-2 gap-y-2" : "grid-cols-1 divide-y divide-edge"}`}>
        {visibleEntries.map((entry, index) => (
          <div key={`${entry.label}-${index}`} className="py-2">
            <p className={`font-medium text-white ${compact ? "text-xs leading-5" : "text-sm"}`}>{entry.label}</p>
            <p className="mt-1 text-xs leading-5 text-slate-400">{entry.detail}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
