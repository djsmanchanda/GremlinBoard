"use client";

import Link from "next/link";
import type { Route } from "next";
import { useEffect, useState } from "react";

import { BoardGrid } from "@/components/board/board-grid";
import { CommandPalette } from "@/components/board/command-palette";
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

interface RemovedWidgetState {
  preset: WidgetPreset;
}

export function BoardShell() {
  const { board, registry, commandOpen, error, setBoard, setRegistry, setCommandOpen, setError } = useBoardStore();
  const [loading, setLoading] = useState(true);
  const [removedWidget, setRemovedWidget] = useState<RemovedWidgetState | null>(null);

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
    void load();
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

  useEffect(() => {
    if (!removedWidget) {
      return;
    }
    const timeout = window.setTimeout(() => setRemovedWidget(null), 6000);
    return () => window.clearTimeout(timeout);
  }, [removedWidget]);

  async function handleAddWidget(preset: WidgetPreset) {
    setError(null);
    try {
      await addWidget(preset);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Failed to add widget");
    }
  }

  async function handleUndoRemove() {
    if (!removedWidget) {
      return;
    }
    const { preset } = removedWidget;
    setRemovedWidget(null);
    setError(null);
    try {
      await addWidget(preset);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Failed to restore widget");
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
    if (!board) {
      return;
    }
    const target = board.widgets.find((widget) => widget.id === widgetId);
    if (!target) {
      return;
    }

    const previousBoard = board;
    setBoard({
      ...board,
      widgets: board.widgets.filter((widget) => widget.id !== widgetId),
    });
    setRemovedWidget({
      preset: {
        key: target.widget_id,
        label: target.title,
        widget_id: target.widget_id,
        title: target.title,
        size: target.size,
        config: target.config,
      },
    });

    try {
      await removeWidget(widgetId);
    } catch (actionError) {
      setBoard(previousBoard);
      setRemovedWidget(null);
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

  const registryCount = Object.keys(registry).length;
  const boardCount = board?.widgets.length ?? 0;

  return (
    <main className="min-h-screen bg-[#05070a] px-4 py-5 md:px-6 md:py-6">
      <section className="mx-auto max-w-7xl">
        <header className="mb-5 rounded-[24px] border border-white/10 bg-[#090c10] p-5 md:p-6">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] uppercase tracking-[0.22em] text-slate-400">
                  Live board
                </span>
                <span className="rounded border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] uppercase tracking-[0.22em] text-slate-400">
                  Strict grid
                </span>
              </div>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white md:text-4xl">GremlinBoard</h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                Compact runtime board for registered widgets only. Drag, resize, refresh, and inspect service state on a fixed square grid.
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              <Link
                href={"/system" as Route}
                className="rounded-[12px] border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-slate-100 transition hover:bg-white/[0.08]"
              >
                System
              </Link>
              <Link
                href="/studio"
                className="rounded-[12px] border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-slate-100 transition hover:bg-white/[0.08]"
              >
                Spec studio
              </Link>
              <button
                type="button"
                onClick={() => setCommandOpen(true)}
                className="rounded-[12px] border border-cyan-300/20 bg-cyan-300/10 px-4 py-2 text-sm text-cyan-50 transition hover:bg-cyan-300/16"
              >
                Add widget
              </button>
            </div>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-3">
            <SummaryCard label="Allowed sizes" value="1x1, 1x2, 2x2, 4x2, 2x4, 4x4" hint="Only approved ratios can be placed." />
            <SummaryCard label="Registry" value={String(registryCount)} hint="Registered widget manifests available." />
            <SummaryCard label="Board" value={String(boardCount)} hint="Widgets currently placed on this board." />
          </div>
        </header>

        {error ? (
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-[18px] border border-rose-300/18 bg-rose-300/8 px-4 py-3 text-sm text-rose-50">
            <div>
              <p className="text-[10px] uppercase tracking-[0.18em] text-rose-200/80">Runtime warning</p>
              <p className="mt-1">{error}</p>
            </div>
            <Link
              href={"/system" as Route}
              className="rounded-[10px] border border-white/10 bg-white/10 px-3 py-2 text-xs uppercase tracking-[0.14em] text-white transition hover:bg-white/15"
            >
              Open system panel
            </Link>
          </div>
        ) : null}

        {loading || !board ? (
          <div className="rounded-[24px] border border-white/10 bg-[#090c10] p-5 md:p-6">
            <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <p className="text-[10px] uppercase tracking-[0.22em] text-slate-500">Board boot</p>
                <h2 className="mt-2 text-2xl font-semibold text-white">
                  {error ? "Board state is unavailable." : "Loading board surface"}
                </h2>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                  {error
                    ? "The latest board snapshot did not load cleanly. Retry or inspect the runtime panel for provider and service failures."
                    : "Fetching the board snapshot, registry manifests, and realtime stream."}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => window.location.reload()}
                  className="rounded-[12px] border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-slate-100 transition hover:bg-white/[0.08]"
                >
                  Retry
                </button>
                <Link
                  href={"/system" as Route}
                  className="rounded-[12px] border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-slate-100 transition hover:bg-white/[0.08]"
                >
                  System panel
                </Link>
              </div>
            </div>

            <div className="mt-6 grid gap-3 md:grid-cols-3">
              {Array.from({ length: 3 }).map((_, index) => (
                <div key={index} className="shimmer rounded-[18px] border border-white/10 bg-white/[0.03] p-4">
                  <div className="h-3 w-20 rounded bg-white/10" />
                  <div className="mt-4 h-6 w-2/3 rounded bg-white/10" />
                  <div className="mt-5 h-28 rounded-[14px] bg-white/[0.05]" />
                </div>
              ))}
            </div>
          </div>
        ) : board.widgets.length === 0 ? (
          <div className="rounded-[24px] border border-white/10 bg-[#090c10] p-5 md:p-6">
            <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
              <div>
                <p className="text-[10px] uppercase tracking-[0.22em] text-slate-500">Empty board</p>
                <h2 className="mt-2 text-3xl font-semibold text-white">Build the first stack</h2>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                  The runtime is up and the board is clear. Start with an existing widget, or stage a generated one through Spec Studio before installation.
                </p>
                <div className="mt-5 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setCommandOpen(true)}
                    className="rounded-[12px] border border-cyan-300/20 bg-cyan-300/10 px-4 py-2 text-sm text-cyan-50 transition hover:bg-cyan-300/16"
                  >
                    Open command box
                  </button>
                  <Link
                    href="/studio"
                    className="rounded-[12px] border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-slate-100 transition hover:bg-white/[0.08]"
                  >
                    Open Spec Studio
                  </Link>
                </div>
              </div>

              <div className="rounded-[18px] border border-white/10 bg-[#07090d] p-4">
                <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Onboarding</p>
                <div className="mt-4 space-y-3">
                  <StepCard index="01" title="Add a core widget" body="Use the command box to place a registered tile on the grid." />
                  <StepCard index="02" title="Arrange the surface" body="Drag to reorder and resize only to approved board ratios." />
                  <StepCard index="03" title="Wire providers" body="Open System Panel if data-backed widgets need API credentials or provider checks." />
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

      {removedWidget ? (
        <div className="fixed bottom-4 left-1/2 z-40 w-[min(420px,calc(100vw-2rem))] -translate-x-1/2 rounded-[16px] border border-white/10 bg-[#0b0f14] px-4 py-3 shadow-[0_24px_60px_rgba(2,6,23,0.45)]">
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="text-sm font-medium text-white">{removedWidget.preset.title} removed</p>
              <p className="mt-1 truncate text-xs text-slate-400">Restore the widget to add it back at the end of the board.</p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={handleUndoRemove}
                className="rounded-[10px] border border-cyan-300/20 bg-cyan-300/10 px-3 py-2 text-xs uppercase tracking-[0.14em] text-cyan-50 transition hover:bg-cyan-300/16"
              >
                Undo
              </button>
              <button
                type="button"
                onClick={() => setRemovedWidget(null)}
                className="rounded-[10px] border border-white/10 bg-white/[0.04] px-3 py-2 text-xs uppercase tracking-[0.14em] text-slate-300 transition hover:bg-white/[0.08]"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <CommandPalette open={commandOpen} onClose={() => setCommandOpen(false)} onSelect={handleAddWidget} />
    </main>
  );
}

function SummaryCard({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-[16px] border border-white/10 bg-[#07090d] px-4 py-3">
      <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">{label}</p>
      <p className="mt-2 text-sm font-medium text-white">{value}</p>
      <p className="mt-1 text-xs text-slate-400">{hint}</p>
    </div>
  );
}

function StepCard({ index, title, body }: { index: string; title: string; body: string }) {
  return (
    <div className="rounded-[16px] border border-white/10 bg-white/[0.03] p-4">
      <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">{index}</p>
      <p className="mt-2 text-sm font-medium text-white">{title}</p>
      <p className="mt-1 text-sm leading-6 text-slate-400">{body}</p>
    </div>
  );
}
