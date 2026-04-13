"use client";

import type { WidgetRendererProps } from "@/lib/types";

export function SportsRenderer({ widget, onUpdateConfig }: WidgetRendererProps) {
  const entries = Array.isArray(widget.state.entries)
    ? (widget.state.entries as Array<{ label: string; detail: string }>)
    : [];
  const activeSport = String(widget.state.sport ?? widget.config.sport ?? "ipl");
  const headline = typeof widget.state.headline === "string" ? widget.state.headline : widget.title;
  const status = typeof widget.state.status === "string" ? widget.state.status : "Live";
  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-start justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-emerald-300/70">Sports</p>
          <h3 className="mt-1 text-lg font-semibold text-white">{headline}</h3>
        </div>
        <span className="rounded-full border border-emerald-300/30 bg-emerald-300/10 px-3 py-1 text-xs text-emerald-100">
          {status}
        </span>
      </div>
      <div className="mb-3 flex flex-wrap gap-2">
        {["ipl", "f1", "football"].map((sport) => (
          <button
            key={sport}
            type="button"
            onClick={() => void onUpdateConfig?.({ ...widget.config, sport })}
            className={`rounded-full px-3 py-1 text-xs transition ${
              activeSport === sport
                ? "border border-emerald-300/30 bg-emerald-300/15 text-emerald-50"
                : "border border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
            }`}
          >
            {sport.toUpperCase()}
          </button>
        ))}
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {entries.map((entry, index) => (
          <div key={`${entry.label}-${index}`} className="rounded-2xl border border-white/10 bg-white/5 p-3">
            <p className="text-sm font-medium text-white">{entry.label}</p>
            <p className="mt-1 text-xs text-slate-400">{entry.detail}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
