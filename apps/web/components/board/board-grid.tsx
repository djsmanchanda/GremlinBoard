"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import {
  BOARD_COLUMNS,
  BOARD_GAP_PX,
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

  const displayWidgets = dragState?.previewWidgets ?? board.widgets;
  const packedLayout = useMemo(() => packBoardLayout(displayWidgets), [displayWidgets]);
  const committedLayout = useMemo(() => packBoardLayout(board.widgets), [board.widgets]);
  const cellWidth =
    containerWidth > 0 ? Math.max((containerWidth - (BOARD_COLUMNS - 1) * BOARD_GAP_PX) / BOARD_COLUMNS, 144) : 176;
  const rowHeight = cellWidth;
  const boardHeight = Math.max(packedLayout.rows, 1) * rowHeight + Math.max(packedLayout.rows - 1, 0) * BOARD_GAP_PX;
  const occupiedCellKeys = new Set(packedLayout.occupiedCells.map((cell) => `${cell.col}-${cell.row}`));
  const previewCellKeys = new Set(
    (selectedId ? packedLayout.occupiedCells.filter((cell) => cell.widgetId === selectedId) : []).map(
      (cell) => `${cell.col}-${cell.row}`,
    ),
  );

  useEffect(() => {
    if (selectedId && !board.widgets.some((widget) => widget.id === selectedId)) {
      setSelectedId(null);
    }
  }, [board.widgets, selectedId]);

  function beginDrag(widgetId: string, event: ReactPointerEvent<HTMLButtonElement>) {
    if (!containerRef.current) {
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

  return (
    <div className="glass-panel-strong premium-ring overflow-x-auto rounded-[34px] p-4 md:p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 px-1">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Live grid</p>
          <p className="mt-1 text-sm text-slate-300">
            Drag tiles to reorder, preview approved sizes on hover, and keep every widget snapped to the strict board grid.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-slate-400">
          <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5">
            {displayWidgets.length} widgets
          </span>
          <span className="rounded-full border border-cyan-300/15 bg-cyan-300/10 px-3 py-1.5 text-cyan-100">
            {selectedId ? `Selected ${selectedId}` : "Select a tile"}
          </span>
        </div>
      </div>
      <div
        ref={containerRef}
        className="relative min-w-[920px] overflow-hidden rounded-[24px] border border-white/8 bg-[#06080b] p-2"
        style={{ height: boardHeight + 16 }}
      >
        {Array.from({ length: Math.max(packedLayout.rows, 4) }).map((_, row) =>
          Array.from({ length: BOARD_COLUMNS }).map((__, col) => {
            const key = `${col}-${row}`;
            const x = col * (cellWidth + BOARD_GAP_PX) + 8;
            const y = row * (rowHeight + BOARD_GAP_PX) + 8;
            return (
              <div
                key={key}
                className={`absolute rounded-[28px] border transition duration-300 ${
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
          if (!manifest) {
            return null;
          }
          const placement = packedLayout.placements[widget.id];
          if (!placement) {
            return null;
          }
          const left = placement.x * (cellWidth + BOARD_GAP_PX) + 8;
          const top = placement.y * (rowHeight + BOARD_GAP_PX) + 8;
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
              <WidgetCard
                widget={widget}
                manifest={manifest}
                configSchema={entry.config_schema}
                plugin={entry.plugin}
                selected={selectedId === widget.id}
                hovered={!dragState && !pendingDrag && hoveredId === widget.id}
                onSelect={() => setSelectedId(widget.id)}
                onHoverChange={(hovered) =>
                  setHoveredId((current) =>
                    dragState || pendingDrag ? current : hovered ? widget.id : current === widget.id ? null : current,
                  )
                }
                onDragHandlePointerDown={(event) => beginDrag(widget.id, event)}
                onResize={(size) => onResize(widget.id, size)}
                onPreviewResize={() => undefined}
                onRefresh={() => onRefresh(widget.id)}
                onToggleRun={() =>
                  onToggleRun(widget.id, widget.lifecycle_state === "running" || widget.lifecycle_state === "created")
                }
                onRemove={() => onRemove(widget.id)}
                onUpdateConfig={(config) => onUpdateConfig(widget.id, config)}
              />
            </div>
          );
        })}

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
              transform: `translate3d(${dragState.ghostX + 8}px, ${dragState.ghostY + 8}px, 0) rotate(1.2deg) scale(1.015)`,
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
                  ghost
                  onSelect={() => undefined}
                  onHoverChange={() => undefined}
                  onDragHandlePointerDown={() => undefined}
                  onResize={() => undefined}
                  onPreviewResize={() => undefined}
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
