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
  const visibleNotes = notes.slice(0, compact ? 1 : tier === "expanded" ? 6 : 3);

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="min-w-0">
        <p className="text-[10px] uppercase tracking-[0.18em] text-amber-300/70">Pinboard</p>
        <h3 className={`mt-1 truncate font-semibold text-white ${compact ? "text-sm" : "text-base"}`}>{widget.title}</h3>
      </div>

      {!compact ? (
        <div className="flex gap-2">
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Add a note"
            className="min-w-0 flex-1 rounded-[12px] border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500"
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
            className="rounded-[12px] border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-xs text-amber-100 transition hover:bg-amber-300/16"
          >
            Pin
          </button>
        </div>
      ) : (
        <div className="rounded-[14px] border border-white/10 bg-white/[0.04] px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Pinned</p>
          <p className="mt-1 text-lg font-semibold text-white">{notes.length}</p>
        </div>
      )}

      <div className="grid gap-2">
        {visibleNotes.length === 0 ? (
          <div className="rounded-[14px] border border-dashed border-white/12 bg-white/[0.03] p-3 text-xs text-slate-400">
            No pinned notes yet.
          </div>
        ) : (
          visibleNotes.map((note) => (
            <div key={note.id} className="rounded-[14px] border border-white/10 bg-white/[0.04] p-3 text-sm leading-5 text-slate-100">
              <p className={compact ? "line-clamp-4 text-xs leading-5" : "line-clamp-3"}>{note.text}</p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
