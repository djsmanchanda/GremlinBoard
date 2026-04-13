"use client";

import { TILE_SIZE_STYLES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { BoardState, JsonObject, WidgetRegistryEntry } from "@/lib/types";
import { WidgetCard } from "@/components/board/widget-card";

interface BoardGridProps {
  board: BoardState;
  registry: Record<string, WidgetRegistryEntry>;
  draggedId: string | null;
  onDragStart: (id: string) => void;
  onDropOn: (id: string) => void;
  onDragEnd: () => void;
  onResize: (widgetId: string, size: keyof typeof TILE_SIZE_STYLES) => void;
  onRefresh: (widgetId: string) => void;
  onToggleRun: (widgetId: string, running: boolean) => void;
  onRemove: (widgetId: string) => void;
  onUpdateConfig: (widgetId: string, config: JsonObject) => void;
}

export function BoardGrid({
  board,
  registry,
  draggedId,
  onDragStart,
  onDropOn,
  onDragEnd,
  onResize,
  onRefresh,
  onToggleRun,
  onRemove,
  onUpdateConfig,
}: BoardGridProps) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-4 md:auto-rows-[148px] md:grid-flow-dense">
      {board.widgets.map((widget) => {
        const manifest = registry[widget.widget_id]?.manifest;
        if (!manifest) {
          return null;
        }
        const sizing = TILE_SIZE_STYLES[widget.size];
        return (
          <div
            key={widget.id}
            draggable
            onDragStart={() => onDragStart(widget.id)}
            onDragEnd={onDragEnd}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => onDropOn(widget.id)}
            className={cn(
              "min-h-[220px] transition-transform duration-150 ease-out",
              sizing.colSpan,
              sizing.rowSpan,
              draggedId === widget.id && "scale-[0.98] opacity-50",
            )}
          >
            <WidgetCard
              widget={widget}
              manifest={manifest}
              onResize={(size) => onResize(widget.id, size)}
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
    </div>
  );
}
