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
            className="min-w-0 flex-1 rounded-none border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500"
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
            className="rounded-none border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-xs text-amber-100 transition hover:bg-amber-300/16"
          >
            Pin
          </button>
        </div>
      ) : (
        <div className="rounded-none border border-white/10 bg-white/[0.04] px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Pinned</p>
          <p className="mt-1 text-lg font-semibold text-white">{notes.length}</p>
        </div>
      )}

      <div className="grid gap-2">
        {visibleNotes.length === 0 ? (
          <div className="rounded-none border border-dashed border-white/12 bg-white/[0.03] p-3 text-xs text-slate-400">
            Nothing pinned.
          </div>
        ) : (
          visibleNotes.map((note) => (
            <div key={note.id} className="rounded-none border border-white/10 bg-white/[0.04] p-2.5 text-sm leading-5 text-slate-100">
              <p className={compact ? "line-clamp-4 text-xs leading-5" : "line-clamp-3"}>{note.text}</p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
