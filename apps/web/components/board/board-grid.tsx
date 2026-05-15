"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import {
  BOARD_GAP_PX,
  MAX_BOARD_COLUMNS,
  MIN_BOARD_COLUMNS,
  TILE_DIMENSIONS,
  findClosestWidgetId,
  packBoardLayout,
  reorderWidgetCollection,
} from "@/lib/board-layout";
import type { BoardState, JsonObject, TileSize, WidgetRegistryEntry } from "@/lib/types";
import { WidgetCard } from "@/components/board/widget-card";

interface BoardGridProps {
  board: BoardState;
  registry: Record<string, WidgetRegistryEntry>;
  onReorder: (orderedIds: string[]) => void | Promise<void>;
  onResize: (widgetId: string, size: TileSize) => void;
  onRefresh: (widgetId: string) => void;
  onToggleRun: (widgetId: string, running: boolean) => void;
  onRemove: (widgetId: string) => void;
  onUpdateConfig: (widgetId: string, config: JsonObject) => void;
}

interface DragState {
  widgetId: string;
  ghostX: number;
  ghostY: number;
  pointerOffsetX: number;
  pointerOffsetY: number;
  previewWidgets: BoardState["widgets"];
}

interface PendingDragState {
  widgetId: string;
  startClientX: number;
  startClientY: number;
  cardX: number;
  cardY: number;
  pointerOffsetX: number;
  pointerOffsetY: number;
}

type BoardMode = "view" | "edit";

export function BoardGrid({
  board,
  registry,
  onReorder,
  onResize,
  onRefresh,
  onToggleRun,
  onRemove,
  onUpdateConfig,
}: BoardGridProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [pendingDrag, setPendingDrag] = useState<PendingDragState | null>(null);
  const [dragState, setDragState] = useState<DragState | null>(null);
  const [resizeState, setResizeState] = useState<ResizeState | null>(null);
  const [showStats, setShowStats] = useState(false);
  const [boardMode, setBoardMode] = useState<BoardMode>("view");
  const resizeCandidateRef = useRef<TileSize | null>(null);
  const isEditMode = boardMode === "edit";

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) {
        return;
      }
      setContainerWidth(entry.contentRect.width);
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const columnCount =
    containerWidth > 0
      ? Math.min(
          MAX_BOARD_COLUMNS,
          Math.max(MIN_BOARD_COLUMNS, Math.floor((containerWidth + BOARD_GAP_PX) / (BOARD_TARGET_CELL_PX + BOARD_GAP_PX))),
        )
      : MIN_BOARD_COLUMNS;
  const displayWidgets = dragState?.previewWidgets ?? board.widgets;
  const packedLayout = useMemo(() => packBoardLayout(displayWidgets, { columns: columnCount }), [columnCount, displayWidgets]);
  const committedLayout = useMemo(() => packBoardLayout(board.widgets, { columns: columnCount }), [board.widgets, columnCount]);
  const cellWidth =
    containerWidth > 0 ? Math.max((containerWidth - (columnCount - 1) * BOARD_GAP_PX) / columnCount, BOARD_MIN_CELL_PX) : 176;
  const rowHeight = cellWidth;
  const visibleRows = Math.max(packedLayout.rows, 4);
  const boardHeight = visibleRows * rowHeight + Math.max(visibleRows - 1, 0) * BOARD_GAP_PX;
  const occupiedCellKeys = new Set(packedLayout.occupiedCells.map((cell) => `${cell.col}-${cell.row}`));
  const previewCellKeys = new Set(
    (isEditMode && selectedId ? packedLayout.occupiedCells.filter((cell) => cell.widgetId === selectedId) : []).map(
      (cell) => `${cell.col}-${cell.row}`,
    ),
  );

  useEffect(() => {
    if (selectedId && !board.widgets.some((widget) => widget.id === selectedId)) {
      setSelectedId(null);
    }
  }, [board.widgets, selectedId]);

  useEffect(() => {
    if (isEditMode) {
      return;
    }
    setPendingDrag(null);
    setDragState(null);
    setResizeState(null);
    setSelectedId(null);
    resizeCandidateRef.current = null;
  }, [isEditMode]);

  function beginDrag(widgetId: string, event: ReactPointerEvent<HTMLDivElement>) {
    if (!isEditMode || !containerRef.current) {
      return;
    }
    event.preventDefault();
    const containerRect = containerRef.current.getBoundingClientRect();
    const placement = committedLayout.placements[widgetId];
    if (!placement) {
      return;
    }
    const cardX = placement.x * (cellWidth + BOARD_GAP_PX);
    const cardY = placement.y * (rowHeight + BOARD_GAP_PX);
    setPendingDrag({
      widgetId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      cardX,
      cardY,
      pointerOffsetX: event.clientX - containerRect.left - cardX,
      pointerOffsetY: event.clientY - containerRect.top - cardY,
    });
  }

  function beginResize(widgetId: string, event: ReactPointerEvent<HTMLDivElement>) {
    if (!isEditMode) {
      return;
    }
    const entry = registry[board.widgets.find((widget) => widget.id === widgetId)?.widget_id ?? ""];
    if (!entry || !containerRef.current) {
      return;
    }
    event.preventDefault();
    const allowedSizes = entry.manifest.allowed_sizes.filter((size) => TILE_DIMENSIONS[size].width <= columnCount);
    const widget = board.widgets.find((item) => item.id === widgetId);
    if (!widget || allowedSizes.length === 0) {
      return;
    }
    resizeCandidateRef.current = widget.size;
    setSelectedId(widgetId);
    setResizeState({
      widgetId,
      allowedSizes,
      candidateSize: widget.size,
    });
  }

  useEffect(() => {
    if ((!dragState && !pendingDrag) || !containerRef.current) {
      return;
    }
    const dragWidgetId = dragState?.widgetId ?? pendingDrag?.widgetId;
    if (!dragWidgetId) {
      return;
    }
    const activeWidgetId = dragWidgetId;

    function handlePointerMove(event: PointerEvent) {
      if (!containerRef.current) {
        return;
      }
      const containerRect = containerRef.current.getBoundingClientRect();
      const localX = event.clientX - containerRect.left;
      const localY = event.clientY - containerRect.top;
      if (dragState == null && pendingDrag != null) {
        const distance = Math.hypot(event.clientX - pendingDrag.startClientX, event.clientY - pendingDrag.startClientY);
        if (distance < 8) {
          return;
        }
        const targetId =
          localY > boardHeight + rowHeight / 2
            ? null
            : findClosestWidgetId(
                committedLayout.orderedPlacements,
                { x: localX, y: localY },
                pendingDrag.widgetId,
                cellWidth,
                rowHeight,
              );
        setSelectedId(pendingDrag.widgetId);
        setPendingDrag(null);
        setDragState({
          widgetId: pendingDrag.widgetId,
          ghostX: localX - pendingDrag.pointerOffsetX,
          ghostY: localY - pendingDrag.pointerOffsetY,
          pointerOffsetX: pendingDrag.pointerOffsetX,
          pointerOffsetY: pendingDrag.pointerOffsetY,
          previewWidgets: reorderWidgetCollection(board.widgets, pendingDrag.widgetId, targetId),
        });
        return;
      }
      const targetId =
        localY > boardHeight + rowHeight / 2
          ? null
          : findClosestWidgetId(
              packedLayout.orderedPlacements,
              { x: localX, y: localY },
              activeWidgetId,
              cellWidth,
              rowHeight,
            );

      setDragState((current) =>
        current
          ? {
              ...current,
              ghostX: localX - current.pointerOffsetX,
              ghostY: localY - current.pointerOffsetY,
              previewWidgets: reorderWidgetCollection(board.widgets, current.widgetId, targetId),
            }
          : current,
      );
    }

    function handlePointerUp() {
      setPendingDrag(null);
      setDragState((current) => {
        if (current) {
          const orderedIds = current.previewWidgets.map((widget) => widget.id);
          const committedIds = board.widgets.map((widget) => widget.id);
          if (orderedIds.join("|") !== committedIds.join("|")) {
            void onReorder(orderedIds);
          }
        }
        return null;
      });
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
  }, [
    board.widgets,
    boardHeight,
    cellWidth,
    committedLayout.orderedPlacements,
    dragState,
    onReorder,
    packedLayout.orderedPlacements,
    pendingDrag,
    rowHeight,
  ]);

  useEffect(() => {
    if (!resizeState || !containerRef.current) {
      return;
    }
    const activeWidgetId = resizeState.widgetId;
    const allowedSizes = resizeState.allowedSizes;

    function handlePointerMove(event: PointerEvent) {
      if (!containerRef.current) {
        return;
      }
      const placement = committedLayout.placements[activeWidgetId];
      if (!placement) {
        return;
      }
      const containerRect = containerRef.current.getBoundingClientRect();
      const localX = event.clientX - containerRect.left;
      const localY = event.clientY - containerRect.top;
      const cardX = placement.x * (cellWidth + BOARD_GAP_PX);
      const cardY = placement.y * (rowHeight + BOARD_GAP_PX);
      const desiredWidth = Math.max(cellWidth * 0.5, localX - cardX);
      const desiredHeight = Math.max(rowHeight * 0.5, localY - cardY);
      const nextSize = findNearestTileSize(allowedSizes, desiredWidth, desiredHeight, cellWidth, rowHeight);
      resizeCandidateRef.current = nextSize;
      setResizeState((current) => (current ? { ...current, candidateSize: nextSize } : current));
    }

    function handlePointerUp() {
      const nextSize = resizeCandidateRef.current;
      const widget = board.widgets.find((item) => item.id === activeWidgetId);
      setResizeState(null);
      resizeCandidateRef.current = null;
      if (widget && nextSize && nextSize !== widget.size) {
        onResize(activeWidgetId, nextSize);
      }
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
  }, [board.widgets, cellWidth, committedLayout.placements, onResize, resizeState, rowHeight]);

  return (
    <div className="glass-panel-strong premium-ring overflow-x-auto rounded-none p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3 px-1">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Monitoring board</p>
          <p className="mt-1 truncate text-sm text-slate-300">
            {isEditMode ? "Edit mode active: layout handles are enabled." : "View mode active: layout is locked for monitoring."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-slate-400">
          <div className="grid grid-cols-2 overflow-hidden rounded border border-white/10 bg-white/[0.04] p-0.5">
            <button
              type="button"
              aria-pressed={!isEditMode}
              onClick={() => setBoardMode("view")}
              className={`px-3 py-1.5 transition ${
                !isEditMode ? "bg-cyan-300/16 text-cyan-50" : "text-slate-400 hover:bg-white/[0.06] hover:text-slate-200"
              }`}
            >
              View
            </button>
            <button
              type="button"
              aria-pressed={isEditMode}
              onClick={() => setBoardMode("edit")}
              className={`px-3 py-1.5 transition ${
                isEditMode ? "bg-amber-300/16 text-amber-50" : "text-slate-400 hover:bg-white/[0.06] hover:text-slate-200"
              }`}
            >
              Edit
            </button>
          </div>
          <button
            type="button"
            aria-pressed={showStats}
            onClick={() => setShowStats((current) => !current)}
            className={`rounded border px-3 py-1.5 transition ${
              showStats
                ? "border-cyan-300/30 bg-cyan-300/14 text-cyan-50"
                : "border-white/10 bg-white/[0.04] text-slate-300 hover:bg-white/[0.08]"
            }`}
          >
            Stats
          </button>
          <span className="rounded border border-white/10 bg-white/[0.04] px-3 py-1.5">
            {displayWidgets.length} widgets
          </span>
          <span className="rounded border border-white/10 bg-white/[0.04] px-3 py-1.5">
            {columnCount} cols
          </span>
          <span className="rounded border border-cyan-300/15 bg-cyan-300/10 px-3 py-1.5 text-cyan-100">
            {isEditMode ? (selectedId ? `Selected ${selectedId}` : "No tile selected") : "Layout locked"}
          </span>
        </div>
      </div>
      <div
        ref={containerRef}
        className="relative min-w-[760px] overflow-hidden rounded-none border border-white/8 bg-[#06080b]"
        style={{ height: boardHeight }}
      >
        {Array.from({ length: visibleRows }).map((_, row) =>
          Array.from({ length: columnCount }).map((__, col) => {
            const key = `${col}-${row}`;
            const x = col * (cellWidth + BOARD_GAP_PX);
            const y = row * (rowHeight + BOARD_GAP_PX);
            return (
              <div
                key={key}
                className={`absolute rounded-none border transition duration-300 ${
                  previewCellKeys.has(key)
                    ? "border-cyan-300/35 bg-cyan-300/12 shadow-[0_0_0_1px_rgba(103,232,249,0.14)]"
                    : occupiedCellKeys.has(key)
                      ? "border-white/8 bg-white/[0.035]"
                      : "border-white/[0.04] bg-white/[0.012]"
                }`}
                style={{
                  left: x,
                  top: y,
                  width: cellWidth,
                  height: rowHeight,
                }}
              />
            );
          }),
        )}

        {displayWidgets.map((widget) => {
          const entry = registry[widget.widget_id];
          const manifest = entry?.manifest;
          const placement = packedLayout.placements[widget.id];
          if (!placement) {
            return null;
          }
          const left = placement.x * (cellWidth + BOARD_GAP_PX);
          const top = placement.y * (rowHeight + BOARD_GAP_PX);
          const width = placement.width * cellWidth + (placement.width - 1) * BOARD_GAP_PX;
          const height = placement.height * rowHeight + (placement.height - 1) * BOARD_GAP_PX;
          const isDragged = dragState?.widgetId === widget.id;

          return (
            <div
              key={widget.id}
              className="absolute will-change-transform transition-[transform,width,height,opacity,filter] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]"
              style={{
                width,
                height,
                transform: `translate3d(${left}px, ${top}px, 0)`,
                opacity: isDragged ? 0.18 : 1,
                filter: isDragged ? "saturate(0.85)" : "none",
              }}
            >
              {manifest ? (
                <WidgetCard
                  widget={widget}
                  manifest={manifest}
                  configSchema={entry.config_schema}
                  plugin={entry.plugin}
                  selected={isEditMode && selectedId === widget.id}
                  hovered={isEditMode && !dragState && !pendingDrag && hoveredId === widget.id}
                  editMode={isEditMode}
                  showStats={showStats}
                  onSelect={() => {
                    if (isEditMode) {
                      setSelectedId(widget.id);
                    }
                  }}
                  onHoverChange={(hovered) =>
                    setHoveredId((current) =>
                      dragState || pendingDrag ? current : hovered ? widget.id : current === widget.id ? null : current,
                    )
                  }
                  onDragHandlePointerDown={(event) => beginDrag(widget.id, event)}
                  onResizeHandlePointerDown={(event) => beginResize(widget.id, event)}
                  onRefresh={() => onRefresh(widget.id)}
                  onToggleRun={() =>
                    onToggleRun(widget.id, widget.lifecycle_state === "running" || widget.lifecycle_state === "created")
                  }
                  onRemove={() => onRemove(widget.id)}
                  onUpdateConfig={(config) => onUpdateConfig(widget.id, config)}
                />
              ) : (
                <UnavailableWidgetCard
                  title={widget.title}
                  widgetId={widget.widget_id}
                  size={widget.size}
                  selected={isEditMode && selectedId === widget.id}
                  editMode={isEditMode}
                  error={widget.last_error ?? "Widget manifest is not registered."}
                  onSelect={() => {
                    if (isEditMode) {
                      setSelectedId(widget.id);
                    }
                  }}
                  onRemove={() => onRemove(widget.id)}
                />
              )}
            </div>
          );
        })}

        {resizeState
          ? (() => {
              const placement = committedLayout.placements[resizeState.widgetId];
              if (!placement) {
                return null;
              }
              const baseLeft = placement.x * (cellWidth + BOARD_GAP_PX);
              const baseTop = placement.y * (rowHeight + BOARD_GAP_PX);
              return resizeState.allowedSizes.map((size, index) => {
                const dimensions = TILE_DIMENSIONS[size];
                const active = resizeState.candidateSize === size;
                const offset = index * 4;
                return (
                  <div
                    key={size}
                    className={`pointer-events-none absolute z-30 border-2 border-dashed transition-[border-color,background-color,opacity,box-shadow] duration-150 ${
                      active
                        ? "border-cyan-200 bg-cyan-300/10 opacity-100 shadow-[0_0_0_1px_rgba(103,232,249,0.22)]"
                        : "border-white/25 bg-white/[0.015] opacity-70"
                    }`}
                    style={{
                      left: baseLeft + offset,
                      top: baseTop + offset,
                      width: dimensions.width * cellWidth + (dimensions.width - 1) * BOARD_GAP_PX,
                      height: dimensions.height * rowHeight + (dimensions.height - 1) * BOARD_GAP_PX,
                    }}
                  />
                );
              });
            })()
          : null}

        {dragState ? (
          <div
            className="pointer-events-none absolute z-20 opacity-95"
            style={{
              width:
                committedLayout.placements[dragState.widgetId].width * cellWidth +
                (committedLayout.placements[dragState.widgetId].width - 1) * BOARD_GAP_PX,
              height:
                committedLayout.placements[dragState.widgetId].height * rowHeight +
                (committedLayout.placements[dragState.widgetId].height - 1) * BOARD_GAP_PX,
              transform: `translate3d(${dragState.ghostX}px, ${dragState.ghostY}px, 0) rotate(1.2deg) scale(1.015)`,
              filter: "drop-shadow(0 24px 70px rgba(8,145,178,0.34))",
            }}
          >
            {(() => {
              const widget = board.widgets.find((item) => item.id === dragState.widgetId);
              if (!widget) {
                return null;
              }
              const entry = registry[widget.widget_id];
              if (!entry) {
                return null;
              }
              return (
                <WidgetCard
                  widget={widget}
                  manifest={entry.manifest}
                  configSchema={entry.config_schema}
                  plugin={entry.plugin}
                  selected
                  hovered={false}
                  editMode
                  ghost
                  showStats={showStats}
                  onSelect={() => undefined}
                  onHoverChange={() => undefined}
                  onDragHandlePointerDown={() => undefined}
                  onResizeHandlePointerDown={() => undefined}
                  onRefresh={() => undefined}
                  onToggleRun={() => undefined}
                  onRemove={() => undefined}
                  onUpdateConfig={() => undefined}
                />
              );
            })()}
          </div>
        ) : null}
      </div>
    </div>
  );
}

interface ResizeState {
  widgetId: string;
  allowedSizes: TileSize[];
  candidateSize: TileSize;
}

const BOARD_TARGET_CELL_PX = 224;
const BOARD_MIN_CELL_PX = 160;

function UnavailableWidgetCard({
  title,
  widgetId,
  size,
  selected,
  editMode,
  error,
  onSelect,
  onRemove,
}: {
  title: string;
  widgetId: string;
  size: TileSize;
  selected: boolean;
  editMode: boolean;
  error: string;
  onSelect: () => void;
  onRemove: () => void;
}) {
  return (
    <div
      className={[
        "flex h-full min-h-0 flex-col justify-between overflow-hidden rounded-none border bg-[#0a0d11] p-4",
        selected ? "border-rose-300/35" : "border-rose-300/18",
      ].join(" ")}
      onClick={onSelect}
    >
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          <span className="h-2 w-2 shrink-0 rounded-none bg-rose-300" />
          <span className="truncate text-[10px] uppercase tracking-[0.18em] text-rose-100/70">Unavailable</span>
          <span className="rounded border border-white/10 px-1.5 py-0.5 text-[9px] uppercase tracking-[0.14em] text-slate-400">
            {size}
          </span>
        </div>
        <h2 className="mt-2 truncate text-lg font-semibold leading-6 tracking-tight text-white">{title}</h2>
        <p className="mt-1 truncate text-xs text-slate-400">{widgetId}</p>
      </div>

      <div className="my-4 rounded-[14px] border border-rose-300/18 bg-rose-300/8 px-3 py-2.5">
        <p className="text-[10px] uppercase tracking-[0.18em] text-rose-100/80">Registry issue</p>
        <p className="mt-1 line-clamp-3 text-xs leading-5 text-rose-50">{error}</p>
      </div>

      {editMode ? (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
          className="w-fit rounded border border-rose-300/20 bg-rose-300/10 px-3 py-2 text-xs uppercase tracking-[0.14em] text-rose-50 transition hover:bg-rose-300/16"
        >
          Remove tile
        </button>
      ) : null}
    </div>
  );
}

function findNearestTileSize(
  sizes: TileSize[],
  desiredWidth: number,
  desiredHeight: number,
  cellWidth: number,
  rowHeight: number,
) {
  let bestSize: TileSize = sizes[0] ?? "1x1";
  let bestDistance = Number.POSITIVE_INFINITY;

  for (const size of sizes) {
    const dimensions = TILE_DIMENSIONS[size];
    const width = dimensions.width * cellWidth + (dimensions.width - 1) * BOARD_GAP_PX;
    const height = dimensions.height * rowHeight + (dimensions.height - 1) * BOARD_GAP_PX;
    const distance = Math.hypot((desiredWidth - width) / cellWidth, (desiredHeight - height) / rowHeight);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestSize = size;
    }
  }

  return bestSize;
}
