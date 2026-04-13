"use client";

import { useState } from "react";

import type { WidgetRendererProps } from "@/lib/types";

export function PinboardRenderer({ widget, onUpdateConfig }: WidgetRendererProps) {
  const notes = Array.isArray(widget.state.notes)
    ? (widget.state.notes as Array<{ id: string; text: string }>)
    : [];
  const [draft, setDraft] = useState("");

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4">
        <p className="text-xs uppercase tracking-[0.24em] text-amber-300/70">Pinboard</p>
        <h3 className="mt-1 text-lg font-semibold text-white">{widget.title}</h3>
      </div>
      <div className="mb-3 flex gap-2">
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Add a note"
          className="flex-1 rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500"
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
          className="rounded-full border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-xs text-amber-100 transition hover:bg-amber-300/20"
        >
          Pin
        </button>
      </div>
      <div className="space-y-3">
        {notes.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-white/15 p-4 text-sm text-slate-400">
            No pinned notes yet.
          </div>
        ) : (
          notes.map((note) => (
            <div key={note.id} className="rounded-2xl border border-white/10 bg-white/5 p-3 text-sm text-slate-100">
              {note.text}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
