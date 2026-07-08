"use client";

import { useState } from "react";

import { getWidgetDisplayTier } from "@/lib/widget-display";
import type { WidgetRendererProps } from "@/lib/types";

export function PinboardRenderer({ widget, onUpdateConfig }: WidgetRendererProps) {
  const notes = Array.isArray(widget.state.notes)
    ? (widget.state.notes as Array<{ id: string; text: string }>)
    : [];
  const [draft, setDraft] = useState("");
  const tier = getWidgetDisplayTier(widget.size);
  const compact = tier === "compact";
  const visibleNotes = notes.slice(0, compact ? 1 : tier === "expanded" ? 8 : 4);

  return (
    <div className="flex h-full flex-col gap-2">
      {!compact ? (
        <div className="flex gap-2">
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Pin a note"
            className="min-w-0 flex-1 rounded-control border border-edge bg-surface-inset px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-edge-strong"
          />
          <button
            type="button"
            onClick={() => {
              if (!draft.trim()) {
                return;
              }
              const nextNotes = [...notes, { id: crypto.randomUUID(), text: draft.trim() }];
              void onUpdateConfig?.({ ...widget.config, notes: nextNotes });
              setDraft("");
            }}
            className="rounded-control border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn transition hover:bg-warn/20"
          >
            Pin
          </button>
        </div>
      ) : (
        <div className="flex items-baseline gap-2">
          <span className="text-lg font-semibold text-white">{notes.length}</span>
          <span className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Pinned</span>
        </div>
      )}

      {visibleNotes.length === 0 ? (
        <p className="p-3 text-xs text-slate-400">Nothing pinned.</p>
      ) : (
        <div className="divide-y divide-edge">
          {visibleNotes.map((note) => (
            <div key={note.id} className="py-2.5 text-sm leading-5 text-slate-100 first:pt-0">
              <p className={compact ? "line-clamp-4 text-xs leading-5" : "line-clamp-3"}>{note.text}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
