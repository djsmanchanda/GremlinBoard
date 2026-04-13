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
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-950/70 px-4 py-20 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-[28px] border border-white/10 bg-slate-950/95 p-4 shadow-2xl">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Command box</p>
            <h2 className="mt-1 text-lg font-semibold text-white">Add widget</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-white/10 px-3 py-1 text-sm text-slate-300 transition hover:bg-white/10"
          >
            Close
          </button>
        </div>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search presets, sports, trending, countdown..."
          className="mt-4 w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-300/50"
        />
        <div className="mt-4 grid gap-3">
          {presets.map((preset) => (
            <button
              key={preset.key}
              type="button"
              onClick={() => {
                onSelect(preset);
                onClose();
              }}
              className={cn(
                "rounded-2xl border border-white/10 bg-white/5 p-4 text-left transition",
                "hover:border-cyan-300/30 hover:bg-cyan-300/10",
              )}
            >
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-medium text-white">{preset.label}</p>
                  <p className="mt-1 text-xs text-slate-400">
                    {preset.widget_id} · size {preset.size}
                  </p>
                </div>
                <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300">
                  Add
                </span>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
