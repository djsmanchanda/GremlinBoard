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
import {
  BOARD_DENSITY_PRESETS,
  canManuallyRefreshWidget,
  getWidgetAlert,
  getWidgetProviderStates,
  readBoardViewSettings,
  writeBoardViewSettings,
} from "@/lib/board-view-settings";
import type { BoardDensityPreset, BoardViewSettings, WidgetAlert } from "@/lib/board-view-settings";
import type { BoardState, JsonObject, TileSize, WidgetRegistryEntry } from "@/lib/types";
import { WidgetCard } from "@/components/board/widget-card";
import { WidgetSettingsPanel } from "@/components/board/widget-settings-panel";

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
  const [resizeState, setResizeState] = useState<ResizeState | null>(null);
  const [viewSettings, setViewSettings] = useState<BoardViewSettings>(() => readBoardViewSettings());
  const resizeCandidateRef = useRef<TileSize | null>(null);
  const densityDefinition = BOARD_DENSITY_PRESETS[viewSettings.density];
  const isEditMode = viewSettings.mode === "edit";

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
          Math.max(
            MIN_BOARD_COLUMNS,
            Math.floor((containerWidth + BOARD_GAP_PX) / (densityDefinition.targetCellPx + BOARD_GAP_PX)),
          ),
        )
      : MIN_BOARD_COLUMNS;
  const committedLayout = useMemo(() => packBoardLayout(board.widgets, { columns: columnCount }), [board.widgets, columnCount]);
  const displayWidgets = dragState?.previewWidgets ?? board.widgets;
  const packedLayout = useMemo(
    () => (displayWidgets === board.widgets ? committedLayout : packBoardLayout(displayWidgets, { columns: columnCount })),
    [board.widgets, columnCount, committedLayout, displayWidgets],
  );
  const cellWidth =
    containerWidth > 0
      ? Math.max((containerWidth - (columnCount - 1) * BOARD_GAP_PX) / columnCount, densityDefinition.minCellPx)
      : densityDefinition.minCellPx;
  const rowHeight = cellWidth;
  const visibleRows = Math.max(packedLayout.rows, 4);
  const boardHeight = visibleRows * rowHeight + Math.max(visibleRows - 1, 0) * BOARD_GAP_PX;
  const occupiedCellKeys = new Set(packedLayout.occupiedCells.map((cell) => `${cell.col}-${cell.row}`));
  const previewCellKeys = new Set(
    (isEditMode && selectedId ? packedLayout.occupiedCells.filter((cell) => cell.widgetId === selectedId) : []).map(
      (cell) => `${cell.col}-${cell.row}`,
    ),
  );
  const alertsByWidgetId = useMemo(() => {
    const alerts: Record<string, WidgetAlert> = {};
    for (const widget of board.widgets) {
      const entry = registry[widget.widget_id];
      alerts[widget.id] = entry
        ? getWidgetAlert(widget, entry.manifest, entry.plugin)
        : { level: "critical", rank: 3, label: "Registry issue", reasons: ["Widget manifest is not registered"] };
    }
    return alerts;
  }, [board.widgets, registry]);
  const alertSummary = useMemo(() => summarizeAlerts(board.widgets, alertsByWidgetId), [alertsByWidgetId, board.widgets]);
  const selectedWidget = selectedId ? board.widgets.find((widget) => widget.id === selectedId) ?? null : null;
  const selectedEntry = selectedWidget ? registry[selectedWidget.widget_id] : null;

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

  function updateViewSettings(patch: Partial<BoardViewSettings>) {
    setViewSettings((current) => {
      const next = { ...current, ...patch };
      writeBoardViewSettings(next);
      return next;
    });
  }

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
    <div className="glass-panel-strong premium-ring relative overflow-x-auto rounded-none p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3 px-1">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Monitoring board</p>
          <p className="mt-1 truncate text-sm text-slate-300">
            {isEditMode
              ? "Edit mode active: layout handles and side inspector are enabled."
              : `${densityDefinition.label}: layout locked with alert priority active.`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-slate-400">
          <div className="grid grid-cols-2 overflow-hidden rounded border border-white/10 bg-white/[0.04] p-0.5">
            <button
              type="button"
              aria-pressed={!isEditMode}
              onClick={() => updateViewSettings({ mode: "view" })}
              className={`px-3 py-1.5 transition ${
                !isEditMode ? "bg-cyan-300/16 text-cyan-50" : "text-slate-400 hover:bg-white/[0.06] hover:text-slate-200"
              }`}
            >
              View
            </button>
            <button
              type="button"
              aria-pressed={isEditMode}
              onClick={() => updateViewSettings({ mode: "edit" })}
              className={`px-3 py-1.5 transition ${
                isEditMode ? "bg-amber-300/16 text-amber-50" : "text-slate-400 hover:bg-white/[0.06] hover:text-slate-200"
              }`}
            >
              Edit
            </button>
          </div>
          <div className="grid grid-cols-3 overflow-hidden rounded border border-white/10 bg-white/[0.04] p-0.5">
            {(Object.keys(BOARD_DENSITY_PRESETS) as BoardDensityPreset[]).map((density) => (
              <button
                key={density}
                type="button"
                title={BOARD_DENSITY_PRESETS[density].description}
                aria-pressed={viewSettings.density === density}
                onClick={() => updateViewSettings({ density })}
                className={`px-2.5 py-1.5 transition ${
                  viewSettings.density === density
                    ? "bg-cyan-300/16 text-cyan-50"
                    : "text-slate-400 hover:bg-white/[0.06] hover:text-slate-200"
                }`}
              >
                {density === "wall-monitor" ? "Wall" : density === "half-display" ? "Half" : "Desk"}
              </button>
            ))}
          </div>
          <button
            type="button"
            aria-pressed={viewSettings.showStats}
            onClick={() => updateViewSettings({ showStats: !viewSettings.showStats })}
            className={`rounded border px-3 py-1.5 transition ${
              viewSettings.showStats
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
          <AlertSummaryBadge summary={alertSummary} />
          <span className="rounded border border-cyan-300/15 bg-cyan-300/10 px-3 py-1.5 text-cyan-100">
            {isEditMode ? (selectedId ? `Selected ${selectedId}` : "No tile selected") : "Layout locked"}
          </span>
        </div>
      </div>
      {alertSummary.highest ? (
        <div className="mb-3 grid gap-2 border border-white/10 bg-[#07090d] px-3 py-2 text-xs text-slate-300 lg:grid-cols-[auto_1fr_auto] lg:items-center">
          <span className={`w-fit rounded border px-2 py-1 text-[10px] uppercase tracking-[0.16em] ${alertToneClass(alertSummary.highest.level)}`}>
            Priority {alertSummary.highest.level}
          </span>
          <span className="min-w-0 truncate">
            {alertSummary.highestWidgetTitle}: {alertSummary.highest.reasons.join(" / ")}
          </span>
          <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
            C{alertSummary.critical} A{alertSummary.alert} Done{alertSummary.completed}
          </span>
        </div>
      ) : null}
      <div
        ref={containerRef}
        className="relative min-w-[760px] overflow-hidden rounded-none border border-white/8 bg-[#06080b]"
        style={{ height: boardHeight, minWidth: densityDefinition.gridMinWidthPx }}
      >
        {Array.from({ length: visibleRows }).map((_, row) =>
          Array.from({ length: columnCount }).map((__, col) => {
            const key = `${col}-${row}`;
            const x = col * (cellWidth + BOARD_GAP_PX);
            const y = row * (rowHeight + BOARD_GAP_PX);
            return (
              <div
                key={key}
                className={`absolute rounded-none border ${
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
              className={`absolute transition-[transform,width,height,opacity] duration-150 ${isDragged ? "will-change-transform" : ""}`}
              style={{
                width,
                height,
                transform: `translate3d(${left}px, ${top}px, 0)`,
                opacity: isDragged ? 0.18 : 1,
                zIndex: isDragged ? 1 : 10 + (alertsByWidgetId[widget.id]?.rank ?? 0) * 10 + (selectedId === widget.id ? 4 : 0),
              }}
            >
              {manifest ? (
                <WidgetCard
                  widget={widget}
                  manifest={manifest}
                  alert={alertsByWidgetId[widget.id]}
                  canRefresh={canManuallyRefreshWidget(manifest)}
                  densityTone={densityDefinition.cardTone}
                  selected={isEditMode && selectedId === widget.id}
                  hovered={isEditMode && !dragState && !pendingDrag && hoveredId === widget.id}
                  editMode={isEditMode}
                  showStats={viewSettings.showStats}
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
                  alert={alertsByWidgetId[widget.id]}
                  canRefresh={canManuallyRefreshWidget(entry.manifest)}
                  densityTone={densityDefinition.cardTone}
                  selected
                  hovered={false}
                  editMode
                  ghost
                  showStats={viewSettings.showStats}
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

      {isEditMode && selectedWidget ? (
        <WidgetInspector
          widget={selectedWidget}
          entry={selectedEntry}
          alert={alertsByWidgetId[selectedWidget.id]}
          canRefresh={selectedEntry ? canManuallyRefreshWidget(selectedEntry.manifest) : false}
          onClose={() => setSelectedId(null)}
          onRefresh={() => onRefresh(selectedWidget.id)}
          onToggleRun={() =>
            onToggleRun(
              selectedWidget.id,
              selectedWidget.lifecycle_state === "running" || selectedWidget.lifecycle_state === "created",
            )
          }
          onRemove={() => onRemove(selectedWidget.id)}
          onUpdateConfig={(config) => onUpdateConfig(selectedWidget.id, config)}
        />
      ) : null}
    </div>
  );
}

interface ResizeState {
  widgetId: string;
  allowedSizes: TileSize[];
  candidateSize: TileSize;
}

interface AlertSummary {
  critical: number;
  alert: number;
  completed: number;
  highest: WidgetAlert | null;
  highestWidgetTitle: string;
}

function summarizeAlerts(widgets: BoardState["widgets"], alertsByWidgetId: Record<string, WidgetAlert>): AlertSummary {
  const summary: AlertSummary = {
    critical: 0,
    alert: 0,
    completed: 0,
    highest: null,
    highestWidgetTitle: "",
  };

  for (const widget of widgets) {
    const alert = alertsByWidgetId[widget.id];
    if (!alert || alert.level === "nominal") {
      continue;
    }
    if (alert.level === "critical") {
      summary.critical += 1;
    } else if (alert.level === "alert") {
      summary.alert += 1;
    } else if (alert.level === "completed") {
      summary.completed += 1;
    }
    if (!summary.highest || alert.rank > summary.highest.rank) {
      summary.highest = alert;
      summary.highestWidgetTitle = widget.title;
    }
  }

  return summary;
}

function AlertSummaryBadge({ summary }: { summary: AlertSummary }) {
  const active = summary.critical + summary.alert + summary.completed;
  if (active === 0) {
    return (
      <span className="rounded border border-emerald-300/15 bg-emerald-300/8 px-3 py-1.5 text-emerald-100">
        Alerts clear
      </span>
    );
  }

  return (
    <span
      className={`rounded border px-3 py-1.5 ${
        summary.critical > 0
          ? alertToneClass("critical")
          : summary.alert > 0
            ? alertToneClass("alert")
            : alertToneClass("completed")
      }`}
    >
      {summary.critical} critical / {summary.alert} alert / {summary.completed} completed
    </span>
  );
}

function alertToneClass(level: WidgetAlert["level"]) {
  if (level === "critical") {
    return "border-rose-300/24 bg-rose-300/10 text-rose-50";
  }
  if (level === "alert") {
    return "border-amber-300/24 bg-amber-300/10 text-amber-50";
  }
  if (level === "completed") {
    return "border-emerald-300/20 bg-emerald-300/8 text-emerald-50";
  }
  return "border-white/10 bg-white/[0.04] text-slate-300";
}

function WidgetInspector({
  widget,
  entry,
  alert,
  canRefresh,
  onClose,
  onRefresh,
  onToggleRun,
  onRemove,
  onUpdateConfig,
}: {
  widget: BoardState["widgets"][number];
  entry?: WidgetRegistryEntry | null;
  alert: WidgetAlert;
  canRefresh: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onToggleRun: () => void;
  onRemove: () => void;
  onUpdateConfig: (config: JsonObject) => void | Promise<void>;
}) {
  const providerStates = getWidgetProviderStates(widget);
  const running = widget.lifecycle_state === "running" || widget.lifecycle_state === "created";

  return (
    <aside className="fixed bottom-5 right-5 top-5 z-50 flex w-[390px] flex-col overflow-hidden border border-white/12 bg-[#080b10] shadow-[0_24px_80px_rgba(0,0,0,0.5)]">
      <div className="border-b border-white/10 px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[10px] uppercase tracking-[0.22em] text-slate-500">Side inspector</p>
            <h2 className="mt-2 truncate text-lg font-semibold text-white">{widget.title}</h2>
            <p className="mt-1 truncate text-xs text-slate-400">
              {widget.widget_id} / {widget.size}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close inspector"
            title="Close"
            onClick={onClose}
            className="flex h-8 w-8 shrink-0 items-center justify-center border border-white/10 bg-white/[0.04] text-slate-300 transition hover:bg-white/[0.08] hover:text-white"
          >
            x
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <div
          className={`border px-3 py-2.5 text-xs ${
            alert.level === "critical"
              ? "border-rose-300/22 bg-rose-300/9 text-rose-50"
              : alert.level === "alert"
                ? "border-amber-300/22 bg-amber-300/9 text-amber-50"
                : alert.level === "completed"
                  ? "border-emerald-300/20 bg-emerald-300/8 text-emerald-50"
                  : "border-cyan-300/16 bg-cyan-300/8 text-cyan-50"
          }`}
        >
          <p className="text-[10px] uppercase tracking-[0.18em] opacity-75">Alert priority</p>
          <p className="mt-1 font-medium">{alert.label}</p>
          {alert.reasons.length > 0 ? <p className="mt-1 leading-5 opacity-90">{alert.reasons.join(" / ")}</p> : null}
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2">
          <InspectorMetric label="Lifecycle" value={widget.lifecycle_state} />
          <InspectorMetric label="Restarts" value={String(widget.restart_count)} />
          <InspectorMetric label="Failures" value={String(widget.consecutive_failures)} />
          <InspectorMetric label="Uptime" value={`${widget.service_uptime_seconds}s`} />
        </div>

        {entry ? (
          <WidgetSettingsPanel
            configSchema={entry.config_schema}
            value={widget.config}
            onSave={onUpdateConfig}
            providerStates={providerStates}
          />
        ) : (
          <div className="mt-4 border border-rose-300/18 bg-rose-300/8 px-3 py-3 text-sm text-rose-50">
            This tile cannot be configured because its manifest is not registered.
          </div>
        )}
      </div>

      <div className={`grid gap-2 border-t border-white/10 p-3 ${canRefresh ? "grid-cols-3" : "grid-cols-2"}`}>
        {canRefresh ? (
          <button
            type="button"
            onClick={onRefresh}
            className="border border-white/10 bg-white/[0.04] px-3 py-2 text-xs uppercase tracking-[0.14em] text-slate-200 transition hover:bg-white/[0.08]"
          >
            Refresh
          </button>
        ) : null}
        <button
          type="button"
          onClick={onToggleRun}
          className="border border-cyan-300/20 bg-cyan-300/10 px-3 py-2 text-xs uppercase tracking-[0.14em] text-cyan-50 transition hover:bg-cyan-300/16"
        >
          {running ? "Pause" : "Start"}
        </button>
        <button
          type="button"
          onClick={onRemove}
          className="border border-rose-300/20 bg-rose-300/10 px-3 py-2 text-xs uppercase tracking-[0.14em] text-rose-50 transition hover:bg-rose-300/16"
        >
          Remove
        </button>
      </div>
    </aside>
  );
}

function InspectorMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-white/10 bg-black/20 px-3 py-2">
      <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <p className="mt-1 truncate text-sm font-medium text-white">{value}</p>
    </div>
  );
}

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
