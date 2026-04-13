"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import {
  BOARD_COLUMNS,
  BOARD_GAP_PX,
  BOARD_ROW_HEIGHT_PX,
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
  const [previewSizes, setPreviewSizes] = useState<Record<string, TileSize>>({});
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
  const packedLayout = useMemo(
    () => packBoardLayout(displayWidgets, { sizeOverrides: previewSizes }),
    [displayWidgets, previewSizes],
  );
  const committedLayout = useMemo(
    () => packBoardLayout(board.widgets, { sizeOverrides: previewSizes }),
    [board.widgets, previewSizes],
  );
  const cellWidth =
    containerWidth > 0 ? Math.max((containerWidth - (BOARD_COLUMNS - 1) * BOARD_GAP_PX) / BOARD_COLUMNS, 120) : 120;
  const boardHeight =
    Math.max(packedLayout.rows, 1) * BOARD_ROW_HEIGHT_PX + Math.max(packedLayout.rows - 1, 0) * BOARD_GAP_PX;
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
    const cardY = placement.y * (BOARD_ROW_HEIGHT_PX + BOARD_GAP_PX);
    setSelectedId(widgetId);
    setDragState({
      widgetId,
      ghostX: cardX,
      ghostY: cardY,
      pointerOffsetX: event.clientX - containerRect.left - cardX,
      pointerOffsetY: event.clientY - containerRect.top - cardY,
      previewWidgets: board.widgets,
    });
  }

  useEffect(() => {
    if (!dragState || !containerRef.current) {
      return;
    }
    const dragWidgetId = dragState.widgetId;

    function handlePointerMove(event: PointerEvent) {
      if (!containerRef.current) {
        return;
      }
      const containerRect = containerRef.current.getBoundingClientRect();
      const localX = event.clientX - containerRect.left;
      const localY = event.clientY - containerRect.top;
      const targetId =
        localY > boardHeight + BOARD_ROW_HEIGHT_PX / 2
            ? null
            : findClosestWidgetId(
                packedLayout.orderedPlacements,
                { x: localX, y: localY },
                dragWidgetId,
                cellWidth,
                BOARD_ROW_HEIGHT_PX,
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
  }, [board.widgets, boardHeight, cellWidth, dragState, onReorder, packedLayout.orderedPlacements]);

  return (
    <div className="overflow-x-auto rounded-[32px] border border-white/10 bg-[rgba(5,10,20,0.48)] p-4 md:p-5">
      <div
        ref={containerRef}
        className="relative min-w-[920px] rounded-[28px] border border-white/8 bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.08),transparent_28%),rgba(6,10,19,0.9)] p-2"
        style={{ height: boardHeight + 16 }}
      >
        {Array.from({ length: Math.max(packedLayout.rows, 4) }).map((_, row) =>
          Array.from({ length: BOARD_COLUMNS }).map((__, col) => {
            const key = `${col}-${row}`;
            const x = col * (cellWidth + BOARD_GAP_PX) + 8;
            const y = row * (BOARD_ROW_HEIGHT_PX + BOARD_GAP_PX) + 8;
            return (
              <div
                key={key}
                className={`absolute rounded-3xl border transition duration-200 ${
                  previewCellKeys.has(key)
                    ? "border-cyan-300/35 bg-cyan-300/10"
                    : occupiedCellKeys.has(key)
                      ? "border-white/8 bg-white/[0.03]"
                      : "border-white/[0.04] bg-white/[0.015]"
                }`}
                style={{
                  left: x,
                  top: y,
                  width: cellWidth,
                  height: BOARD_ROW_HEIGHT_PX,
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
          const top = placement.y * (BOARD_ROW_HEIGHT_PX + BOARD_GAP_PX) + 8;
          const width = placement.width * cellWidth + (placement.width - 1) * BOARD_GAP_PX;
          const height = placement.height * BOARD_ROW_HEIGHT_PX + (placement.height - 1) * BOARD_GAP_PX;
          const isDragged = dragState?.widgetId === widget.id;

          return (
            <div
              key={widget.id}
              className="absolute transition-[transform,width,height,opacity] duration-300 ease-out"
              style={{
                width,
                height,
                transform: `translate3d(${left}px, ${top}px, 0)`,
                opacity: isDragged ? 0.24 : 1,
              }}
            >
              <WidgetCard
                widget={widget}
                manifest={manifest}
                plugin={entry.plugin}
                selected={selectedId === widget.id}
                hovered={hoveredId === widget.id}
                onSelect={() => setSelectedId(widget.id)}
                onHoverChange={(hovered) =>
                  setHoveredId((current) => (hovered ? widget.id : current === widget.id ? null : current))
                }
                onDragHandlePointerDown={(event) => beginDrag(widget.id, event)}
                onResize={(size) => {
                  setPreviewSizes((current) => {
                    const next = { ...current };
                    delete next[widget.id];
                    return next;
                  });
                  onResize(widget.id, size);
                }}
                onPreviewResize={(size) =>
                  setPreviewSizes((current) => {
                    const next = { ...current };
                    if (size) {
                      next[widget.id] = size;
                    } else {
                      delete next[widget.id];
                    }
                    return next;
                  })
                }
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
                committedLayout.placements[dragState.widgetId].height * BOARD_ROW_HEIGHT_PX +
                (committedLayout.placements[dragState.widgetId].height - 1) * BOARD_GAP_PX,
              transform: `translate3d(${dragState.ghostX + 8}px, ${dragState.ghostY + 8}px, 0) rotate(1deg)`,
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
