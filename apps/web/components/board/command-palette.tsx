"use client";

import { useMemo, useState } from "react";

import { WIDGET_PRESETS } from "@/lib/widget-presets";
import { cn } from "@/lib/utils";
import type { WidgetPreset } from "@/lib/types";

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  onSelect: (preset: WidgetPreset) => void;
}

export function CommandPalette({ open, onClose, onSelect }: CommandPaletteProps) {
  const [query, setQuery] = useState("");

  const presets = useMemo(() => {
    if (!query) {
      return WIDGET_PRESETS;
    }
    const needle = query.toLowerCase();
    return WIDGET_PRESETS.filter(
      (preset) =>
        preset.label.toLowerCase().includes(needle) ||
        preset.title.toLowerCase().includes(needle) ||
        preset.widget_id.toLowerCase().includes(needle),
    );
  }, [query]);

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-950/72 px-4 py-20 backdrop-blur-md">
      <div className="glass-panel-strong accent-border w-full max-w-2xl rounded-[32px] p-5 shadow-2xl">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Command box</p>
            <h2 className="mt-1 text-lg font-semibold text-white">Add widget</h2>
            <p className="mt-2 text-sm text-slate-400">Search the approved registry and place a widget on the board.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-white/10 px-3 py-1 text-sm text-slate-300 transition duration-200 hover:-translate-y-0.5 hover:bg-white/10"
          >
            Close
          </button>
        </div>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search presets, sports, trending, countdown..."
          className="mt-5 w-full rounded-[22px] border border-white/10 bg-white/5 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500 transition focus:border-cyan-300/50"
        />
        <div className="mt-5 grid gap-3">
          {presets.length === 0 ? (
            <div className="rounded-[26px] border border-dashed border-white/12 bg-white/[0.03] p-6 text-center">
              <p className="text-sm font-medium text-white">No preset matched that search.</p>
              <p className="mt-2 text-sm text-slate-400">Try widget ids like `news`, `sports`, or `countdown`.</p>
            </div>
          ) : (
            presets.map((preset) => (
              <button
                key={preset.key}
                type="button"
                onClick={() => {
                  onSelect(preset);
                  onClose();
                }}
                className={cn(
                  "rounded-[24px] border border-white/10 bg-white/[0.04] p-4 text-left transition duration-200",
                  "hover:-translate-y-0.5 hover:border-cyan-300/30 hover:bg-cyan-300/10",
                )}
              >
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium text-white">{preset.label}</p>
                      <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-slate-400">
                        {preset.size}
                      </span>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-slate-400">
                      {preset.widget_id} · {preset.title}
                    </p>
                  </div>
                  <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300">
                    Add
                  </span>
                </div>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
