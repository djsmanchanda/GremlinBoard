"use client";

import Link from "next/link";
import type { Route } from "next";
import { useEffect, useState } from "react";

import {
  addWidget,
  fetchBoard,
  fetchRegistry,
  refreshWidget,
  removeWidget,
  reorderWidgets,
  resizeWidget,
  startWidget,
  stopWidget,
  updateWidget,
} from "@/lib/api";
import { API_BASE_URL } from "@/lib/constants";
import type { BoardState, JsonObject, WidgetPreset } from "@/lib/types";
import { useBoardStore } from "@/store/board-store";
import { BoardGrid } from "@/components/board/board-grid";
import { CommandPalette } from "@/components/board/command-palette";

export function BoardShell() {
  const {
    board,
    registry,
    commandOpen,
    error,
    setBoard,
    setRegistry,
    setCommandOpen,
    setError,
  } = useBoardStore();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [boardResponse, registryResponse] = await Promise.all([fetchBoard(), fetchRegistry()]);
        if (cancelled) {
          return;
        }
        setBoard(boardResponse);
        setRegistry(registryResponse);
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Failed to load board");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [setBoard, setError, setRegistry]);

  useEffect(() => {
    const socketUrl = `${API_BASE_URL.replace(/^http/, "ws")}/board/stream`;
    const socket = new WebSocket(socketUrl);
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as { type: string; payload: BoardState };
      if (payload.type === "board.snapshot") {
        setBoard(payload.payload);
      }
    };
    socket.onerror = () => setError("Realtime board stream disconnected");
    return () => socket.close();
  }, [setBoard, setError]);

  async function handleAddWidget(preset: WidgetPreset) {
    setError(null);
    try {
      await addWidget(preset);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Failed to add widget");
    }
  }

  async function handleResize(widgetId: string, size: WidgetPreset["size"]) {
    if (board) {
      setBoard({
        ...board,
        widgets: board.widgets.map((widget) => (widget.id === widgetId ? { ...widget, size } : widget)),
      });
    }
    try {
      await resizeWidget(widgetId, size);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Failed to resize widget");
    }
  }

  async function handleRefresh(widgetId: string) {
    try {
      await refreshWidget(widgetId);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Failed to refresh widget");
    }
  }

  async function handleToggleRun(widgetId: string, running: boolean) {
    try {
      if (running) {
        await stopWidget(widgetId);
      } else {
        await startWidget(widgetId);
      }
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Failed to update widget lifecycle");
    }
  }

  async function handleRemove(widgetId: string) {
    try {
      await removeWidget(widgetId);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Failed to remove widget");
    }
  }

  async function handleUpdateConfig(widgetId: string, config: JsonObject) {
    try {
      await updateWidget(widgetId, { config });
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Failed to update widget config");
    }
  }

  async function handleReorder(orderedIds: string[]) {
    if (!board) {
      return;
    }
    const widgetsById = new Map(board.widgets.map((widget) => [widget.id, widget]));
    const optimisticBoard: BoardState = {
      ...board,
      widgets: orderedIds.map((id) => widgetsById.get(id)).filter(Boolean) as BoardState["widgets"],
    };
    setBoard(optimisticBoard);
    try {
      await reorderWidgets(orderedIds);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Failed to reorder widgets");
    }
  }

  return (
    <main className="min-h-screen px-4 py-6 md:px-6 md:py-8">
      <section className="mx-auto max-w-7xl">
        <header className="glass-panel accent-border premium-ring mb-6 overflow-hidden rounded-[36px] p-6 md:p-7">
          <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <div className="max-w-3xl">
              <div className="flex flex-wrap items-center gap-3">
                <span className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-3 py-1 text-[11px] uppercase tracking-[0.28em] text-cyan-100">
                  OpenClaw Runtime Board
                </span>
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] uppercase tracking-[0.24em] text-slate-300">
                  Live control surface
                </span>
              </div>
              <h1 className="mt-4 text-4xl font-semibold tracking-tight text-white md:text-5xl">
                <span className="text-gradient">GremlinBoard</span>
              </h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">
                Strict registry. Fixed grid sizes only. Python-backed widget microservices with persisted state,
                scheduled refresh, lifecycle controls, and spec-first widget staging.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Link
                href={"/system" as Route}
                className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-100 transition duration-200 hover:-translate-y-0.5 hover:bg-white/10"
              >
                System
              </Link>
              <Link
                href="/studio"
                className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-100 transition duration-200 hover:-translate-y-0.5 hover:bg-white/10"
              >
                Spec studio
              </Link>
              <button
                type="button"
                onClick={() => setCommandOpen(true)}
                className="rounded-full border border-cyan-300/20 bg-cyan-300/12 px-4 py-2 text-sm text-cyan-50 shadow-[0_12px_40px_rgba(34,211,238,0.16)] transition duration-200 hover:-translate-y-0.5 hover:bg-cyan-300/18"
              >
                Add widget
              </button>
            </div>
          </div>

          <div className="mt-6 grid gap-3 md:grid-cols-3">
            <div className="rounded-[24px] border border-white/10 bg-black/20 px-4 py-4">
              <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Allowed sizes</p>
              <p className="mt-2 text-sm font-medium text-white">1x1, 1x2, 2x2, 4x2, 2x4, 4x4</p>
            </div>
            <div className="rounded-[24px] border border-white/10 bg-black/20 px-4 py-4">
              <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Registry coverage</p>
              <p className="mt-2 text-2xl font-semibold text-white">{Object.keys(registry).length}</p>
              <p className="mt-1 text-xs text-slate-400">Registered widget manifests available</p>
            </div>
            <div className="rounded-[24px] border border-white/10 bg-black/20 px-4 py-4">
              <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Board occupancy</p>
              <p className="mt-2 text-2xl font-semibold text-white">{board?.widgets.length ?? 0}</p>
              <p className="mt-1 text-xs text-slate-400">Active tiles on the current board</p>
            </div>
          </div>
        </header>

        {error ? (
          <div className="glass-panel accent-border mb-4 rounded-[28px] px-5 py-4 text-sm text-rose-50">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-[0.2em] text-rose-200/80">Board signal degraded</p>
                <p className="mt-1 text-sm text-rose-50">{error}</p>
              </div>
              <Link
                href={"/system" as Route}
                className="rounded-full border border-white/10 bg-white/10 px-4 py-2 text-xs uppercase tracking-[0.18em] text-white transition hover:bg-white/15"
              >
                Inspect runtime
              </Link>
            </div>
          </div>
        ) : null}

        {loading || !board ? (
          <div className="glass-panel-strong premium-ring rounded-[32px] p-6 md:p-7">
            <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.28em] text-slate-500">Board boot</p>
                <h2 className="mt-2 text-2xl font-semibold text-white">
                  {error ? "Board state is unavailable." : "Hydrating the control surface"}
                </h2>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
                  {error
                    ? "The board snapshot did not arrive cleanly. You can retry or open the system panel to inspect runtime health."
                    : "Fetching the latest widget registry, layout snapshot, and realtime stream before rendering the board."}
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => window.location.reload()}
                  className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-100 transition hover:bg-white/10"
                >
                  Retry load
                </button>
                <Link
                  href={"/system" as Route}
                  className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-100 transition hover:bg-white/10"
                >
                  Open system panel
                </Link>
              </div>
            </div>

            <div className="mt-6 grid gap-4 md:grid-cols-3">
              {Array.from({ length: 3 }).map((_, index) => (
                <div
                  key={index}
                  className="shimmer rounded-[28px] border border-white/10 bg-white/[0.04] p-5"
                >
                  <div className="h-3 w-24 rounded-full bg-white/10" />
                  <div className="mt-4 h-8 w-3/4 rounded-full bg-white/10" />
                  <div className="mt-6 h-32 rounded-[24px] bg-white/[0.06]" />
                </div>
              ))}
            </div>
          </div>
        ) : board.widgets.length === 0 ? (
          <div className="glass-panel-strong accent-border premium-ring rounded-[32px] p-6 md:p-7">
            <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr] lg:items-start">
              <div>
                <p className="text-xs uppercase tracking-[0.28em] text-cyan-200/70">Board ready</p>
                <h2 className="mt-2 text-3xl font-semibold text-white">Start with a curated widget stack</h2>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
                  The runtime is live, the registry is loaded, and the board is empty. Add a widget from the command box
                  or build one through the staged Spec Studio workflow.
                </p>
                <div className="mt-5 flex flex-wrap gap-3">
                  <button
                    type="button"
                    onClick={() => setCommandOpen(true)}
                    className="rounded-full border border-cyan-300/20 bg-cyan-300/12 px-4 py-2 text-sm text-cyan-50 transition hover:bg-cyan-300/18"
                  >
                    Open command box
                  </button>
                  <Link
                    href="/studio"
                    className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-100 transition hover:bg-white/10"
                  >
                    Open Spec Studio
                  </Link>
                </div>
              </div>

              <div className="surface-grid rounded-[30px] border border-white/10 bg-black/20 p-5">
                <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Suggested first tiles</p>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  {[
                    "Trending feed",
                    "News monitor",
                    "Sports pulse",
                    "Countdown",
                  ].map((label) => (
                    <div key={label} className="rounded-[22px] border border-white/10 bg-white/[0.04] p-4">
                      <p className="text-sm font-medium text-white">{label}</p>
                      <p className="mt-2 text-xs leading-5 text-slate-400">
                        Add from the command box, then drag into place and resize using the approved grid ratios.
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        ) : (
          <BoardGrid
            board={board}
            registry={registry}
            onReorder={handleReorder}
            onResize={handleResize}
            onRefresh={handleRefresh}
            onToggleRun={handleToggleRun}
            onRemove={handleRemove}
            onUpdateConfig={handleUpdateConfig}
          />
        )}
      </section>
      <CommandPalette
        open={commandOpen}
        onClose={() => setCommandOpen(false)}
        onSelect={handleAddWidget}
      />
    </main>
  );
}
