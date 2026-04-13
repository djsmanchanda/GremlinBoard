"use client";

import Link from "next/link";
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
    <main className="min-h-screen px-4 py-6 md:px-6">
      <section className="mx-auto max-w-7xl">
        <header className="mb-6 flex flex-col gap-4 rounded-[32px] border border-white/10 bg-white/5 p-5 backdrop-blur md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-cyan-300/80">OpenClaw Runtime Board</p>
            <h1 className="mt-2 text-4xl font-semibold tracking-tight text-white">GremlinBoard MVP</h1>
            <p className="mt-3 max-w-3xl text-sm text-slate-300">
              Strict registry. Fixed grid sizes only. Python-backed widget microservices with persisted state,
              scheduled refresh, lifecycle controls, and spec-first widget staging.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/studio"
              className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/10"
            >
              Spec studio
            </Link>
            <button
              type="button"
              onClick={() => setCommandOpen(true)}
              className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-4 py-2 text-sm text-cyan-100 transition hover:bg-cyan-300/20"
            >
              Add widget
            </button>
          </div>
        </header>

        {error ? (
          <div className="mb-4 rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
            {error}
          </div>
        ) : null}

        <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-slate-400">
          <span className="rounded-full border border-white/10 px-3 py-1">Allowed sizes: 1x1, 1x2, 2x2, 4x2, 2x4, 4x4</span>
          <span className="rounded-full border border-white/10 px-3 py-1">
            Registry widgets: {Object.keys(registry).length}
          </span>
          <span className="rounded-full border border-white/10 px-3 py-1">
            Active tiles: {board?.widgets.length ?? 0}
          </span>
        </div>

        {loading || !board ? (
          <div className="rounded-[28px] border border-white/10 bg-white/5 p-8 text-sm text-slate-300">
            Loading board runtime...
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
