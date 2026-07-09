"use client";

import Link from "next/link";
import type { Route } from "next";
import { useCallback, useEffect, useRef, useState } from "react";

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
import { applyBoardEvent, type BoardProjectionState } from "@/lib/board-reconciliation";
import { apiWebSocketUrl } from "@/lib/constants";
import type { BoardPatch, BoardState, JsonObject, RuntimeEventMessage, WidgetPreset } from "@/lib/types";
import { useBoardStore } from "@/store/board-store";

interface RemovedWidgetState {
  preset: WidgetPreset;
}

export function BoardShell() {
  const { board, registry, commandOpen, error, setBoard, setRegistry, setCommandOpen, setError } = useBoardStore();
  const [loading, setLoading] = useState(true);
  const [removedWidget, setRemovedWidget] = useState<RemovedWidgetState | null>(null);
  const hasBoardSnapshot = useRef(false);
  const hasRegistrySnapshot = useRef(false);
  const registryRefreshInFlight = useRef(false);
  const projection = useRef<BoardProjectionState>({ board: null, lastSequence: 0, needsSnapshot: false });

  const commitBoard = useCallback((nextBoard: BoardState, sequence = projection.current.lastSequence) => {
    projection.current = {
      board: nextBoard,
      lastSequence: sequence,
      needsSnapshot: false,
    };
    setBoard(nextBoard);
  }, [setBoard]);

  useEffect(() => {
    hasRegistrySnapshot.current = Object.keys(registry).length > 0;
  }, [registry]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [boardResponse, registryResponse] = await Promise.all([fetchBoard(), fetchRegistry()]);
        if (cancelled) {
          return;
        }
        commitBoard(boardResponse, projection.current.lastSequence);
        setRegistry(registryResponse);
        hasBoardSnapshot.current = true;
        setError(null);
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
  }, [commitBoard, setError, setRegistry]);

  useEffect(() => {
    let closed = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let reconnectAttempt = 0;

    const clearReconnect = () => {
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const closeSocket = () => {
      clearReconnect();
      const activeSocket = socket;
      socket = null;
      activeSocket?.close();
    };

    const scheduleReconnect = () => {
      if (closed || document.visibilityState !== "visible" || reconnectTimer !== null) {
        return;
      }
      const delay = Math.min(30000, 1000 * 2 ** reconnectAttempt);
      reconnectAttempt += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    };

    const refreshRegistrySnapshot = () => {
      if (registryRefreshInFlight.current) {
        return;
      }
      registryRefreshInFlight.current = true;
      void fetchRegistry()
        .then((registryResponse) => {
          setRegistry(registryResponse);
          hasRegistrySnapshot.current = Object.keys(registryResponse).length > 0;
          setError(null);
        })
        .catch((loadError) => {
          setError(loadError instanceof Error ? loadError.message : "Failed to refresh widget registry");
        })
        .finally(() => {
          registryRefreshInFlight.current = false;
        });
    };
    const commitProjectedBoard = (nextProjection: BoardProjectionState) => {
      projection.current = nextProjection;
      if (nextProjection.board) {
        commitBoard(nextProjection.board, nextProjection.lastSequence);
      }
      hasBoardSnapshot.current = true;
      setError(null);
      if (!hasRegistrySnapshot.current) {
        refreshRegistrySnapshot();
      }
    };

    const fetchSnapshotFallback = () => {
      void fetchBoard()
        .then((snapshot) => {
          commitProjectedBoard({
            board: snapshot,
            lastSequence: projection.current.lastSequence,
            needsSnapshot: false,
          });
        })
        .catch((loadError) => {
          setError(loadError instanceof Error ? loadError.message : "Failed to recover board snapshot");
        });
    };

    const connect = () => {
      if (closed || socket || document.visibilityState === "hidden") {
        return;
      }
      const lastSequence = projection.current.lastSequence;
      const streamPath = lastSequence > 0 ? `/board/stream?last_seq=${lastSequence}` : "/board/stream";
      const nextSocket = new WebSocket(apiWebSocketUrl(streamPath));
      socket = nextSocket;
      nextSocket.onopen = () => {
        reconnectAttempt = 0;
      };
      nextSocket.onmessage = (event) => {
        reconnectAttempt = 0;
        const payload = JSON.parse(event.data) as RuntimeEventMessage<BoardState | BoardPatch>;
        const projected = applyBoardEvent(projection.current, payload);
        projection.current = projected.state;
        if (projected.kind === "snapshot_required") {
          fetchSnapshotFallback();
          return;
        }
        if (projected.kind === "applied") {
          commitProjectedBoard(projected.state);
          return;
        }
        if (payload.type === "registry.updated") {
          refreshRegistrySnapshot();
        }
      };
      nextSocket.onerror = () => {
        if (!hasBoardSnapshot.current) {
          setError("Realtime board stream disconnected");
        }
      };
      nextSocket.onclose = () => {
        if (socket !== nextSocket) {
          return;
        }
        socket = null;
        scheduleReconnect();
      };
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        closeSocket();
        return;
      }
      void fetchBoard()
        .then((snapshot) => {
          commitProjectedBoard({
            board: snapshot,
            lastSequence: projection.current.lastSequence,
            needsSnapshot: false,
          });
          hasBoardSnapshot.current = true;
          setError(null);
        })
        .catch(() => undefined);
      connect();
    };

    connect();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      closed = true;
      closeSocket();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [commitBoard, setError, setRegistry]);

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
      commitBoard({
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
      const boardResponse = await refreshWidget(widgetId);
      commitBoard(boardResponse);
      setError(null);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Failed to refresh widget");
    }
  }

  async function handleToggleRun(widgetId: string, running: boolean) {
    try {
      let boardResponse: BoardState;
      if (running) {
        boardResponse = await stopWidget(widgetId);
      } else {
        boardResponse = await startWidget(widgetId);
      }
      commitBoard(boardResponse);
      setError(null);
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
    commitBoard({
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
      commitBoard(previousBoard);
      setRemovedWidget(null);
      setError(actionError instanceof Error ? actionError.message : "Failed to remove widget");
    }
  }

  async function handleUpdateConfig(widgetId: string, config: JsonObject) {
    const previousBoard = board;
    if (board) {
      commitBoard({
        ...board,
        widgets: board.widgets.map((widget) => (widget.id === widgetId ? { ...widget, config } : widget)),
      });
    }
    try {
      await updateWidget(widgetId, { config });
    } catch (actionError) {
      if (previousBoard) {
        commitBoard(previousBoard);
      }
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
    commitBoard(optimisticBoard);
    try {
      await reorderWidgets(orderedIds);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Failed to reorder widgets");
    }
  }

  return (
    <main className="min-h-screen bg-bg px-2.5 py-4 md:px-4 md:py-5 2xl:px-5">
      <section className="mx-auto w-full max-w-[2520px]">
        <header className="mb-4 flex flex-col gap-3 rounded-panel border border-edge bg-surface px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight text-white">GremlinBoard</h1>
            <p className="mt-1 truncate text-sm text-slate-400">
              Monitoring-station board for registered widgets only.
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <Link
              href={"/system" as Route}
              className="rounded-control border border-edge bg-surface-raised px-4 py-2 text-sm text-slate-100 transition hover:bg-white/[0.08]"
            >
              System
            </Link>
            <Link
              href="/studio"
              className="rounded-control border border-edge bg-surface-raised px-4 py-2 text-sm text-slate-100 transition hover:bg-white/[0.08]"
            >
              Spec studio
            </Link>
            <button
              type="button"
              onClick={() => setCommandOpen(true)}
              className="rounded-control border border-cyan-300/20 bg-cyan-300/10 px-4 py-2 text-sm text-cyan-50 transition hover:bg-cyan-300/16"
            >
              Add widget
            </button>
          </div>
        </header>

        {error ? (
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-panel border border-rose-300/18 bg-rose-300/8 px-4 py-3 text-sm text-rose-50">
            <div>
              <p className="text-[10px] uppercase tracking-[0.18em] text-rose-200/80">Runtime warning</p>
              <p className="mt-1">{error}</p>
            </div>
            <Link
              href={"/system" as Route}
              className="rounded-control border border-edge bg-white/10 px-3 py-2 text-xs uppercase tracking-[0.14em] text-white transition hover:bg-white/15"
            >
              Open system panel
            </Link>
          </div>
        ) : null}

        {loading || !board ? (
          <div className="flex flex-col gap-3 rounded-panel border border-edge bg-surface px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-white">
                {error ? "Board state is unavailable." : "Loading board surface"}
              </h2>
              <p className="mt-1 text-sm text-slate-400">
                {error
                  ? "The latest board snapshot did not load cleanly. Retry or inspect the runtime panel."
                  : "Fetching the board snapshot, registry manifests, and realtime stream."}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="rounded-control border border-edge bg-surface-raised px-4 py-2 text-sm text-slate-100 transition hover:bg-white/[0.08]"
              >
                Retry
              </button>
              <Link
                href={"/system" as Route}
                className="rounded-control border border-edge bg-surface-raised px-4 py-2 text-sm text-slate-100 transition hover:bg-white/[0.08]"
              >
                System panel
              </Link>
            </div>
          </div>
        ) : board.widgets.length === 0 ? (
          <div className="flex flex-col gap-3 rounded-panel border border-edge bg-surface px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-white">Build the first stack</h2>
              <p className="mt-1 text-sm text-slate-400">
                The board is clear. Add a registered widget, or stage a generated one through Spec Studio.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setCommandOpen(true)}
                className="rounded-control border border-cyan-300/20 bg-cyan-300/10 px-4 py-2 text-sm text-cyan-50 transition hover:bg-cyan-300/16"
              >
                Open command box
              </button>
              <Link
                href="/studio"
                className="rounded-control border border-edge bg-surface-raised px-4 py-2 text-sm text-slate-100 transition hover:bg-white/[0.08]"
              >
                Open Spec Studio
              </Link>
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
        <div className="fixed bottom-4 left-1/2 z-40 w-[min(420px,calc(100vw-2rem))] -translate-x-1/2 rounded-panel border border-edge bg-surface-raised px-4 py-3 shadow-[0_24px_60px_rgba(2,6,23,0.45)]">
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="text-sm font-medium text-white">{removedWidget.preset.title} removed</p>
              <p className="mt-1 truncate text-xs text-slate-400">Restore the widget to add it back at the end of the board.</p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={handleUndoRemove}
                className="rounded-control border border-cyan-300/20 bg-cyan-300/10 px-3 py-2 text-xs uppercase tracking-[0.14em] text-cyan-50 transition hover:bg-cyan-300/16"
              >
                Undo
              </button>
              <button
                type="button"
                onClick={() => setRemovedWidget(null)}
                className="rounded-control border border-edge bg-surface-raised px-3 py-2 text-xs uppercase tracking-[0.14em] text-slate-300 transition hover:bg-white/[0.08]"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <CommandPalette
        open={commandOpen}
        registry={registry}
        onClose={() => setCommandOpen(false)}
        onSelect={handleAddWidget}
      />
    </main>
  );
}
