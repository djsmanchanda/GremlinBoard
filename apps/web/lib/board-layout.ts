import type { TileSize, WidgetInstance } from "@/lib/types";

export const BOARD_COLUMNS = 4;
export const BOARD_GAP_PX = 16;
export const BOARD_ROW_HEIGHT_PX = 148;

const TILE_DIMENSIONS: Record<TileSize, { width: number; height: number }> = {
  "1x1": { width: 1, height: 1 },
  "1x2": { width: 1, height: 2 },
  "2x2": { width: 2, height: 2 },
  "4x2": { width: 4, height: 2 },
  "2x4": { width: 2, height: 4 },
  "4x4": { width: 4, height: 4 },
};

export interface PackedPlacement {
  widgetId: string;
  x: number;
  y: number;
  width: number;
  height: number;
  size: TileSize;
}

export interface PackedBoardLayout {
  placements: Record<string, PackedPlacement>;
  orderedPlacements: PackedPlacement[];
  occupiedCells: Array<{ col: number; row: number; widgetId: string }>;
  rows: number;
}

export function packBoardLayout(
  widgets: WidgetInstance[],
  options?: {
    sizeOverrides?: Record<string, TileSize>;
  },
): PackedBoardLayout {
  const occupancy: boolean[][] = [];
  const placements: Record<string, PackedPlacement> = {};
  const orderedPlacements: PackedPlacement[] = [];
  const occupiedCells: Array<{ col: number; row: number; widgetId: string }> = [];

  for (const widget of widgets) {
    const size = options?.sizeOverrides?.[widget.id] ?? widget.size;
    const dimensions = TILE_DIMENSIONS[size];
    const { col, row } = findSlot(occupancy, dimensions.width, dimensions.height);
    markOccupied(occupancy, col, row, dimensions.width, dimensions.height);
    const placement: PackedPlacement = {
      widgetId: widget.id,
      x: col,
      y: row,
      width: dimensions.width,
      height: dimensions.height,
      size,
    };
    placements[widget.id] = placement;
    orderedPlacements.push(placement);
    for (let dy = 0; dy < dimensions.height; dy += 1) {
      for (let dx = 0; dx < dimensions.width; dx += 1) {
        occupiedCells.push({ col: col + dx, row: row + dy, widgetId: widget.id });
      }
    }
  }

  const rows = orderedPlacements.reduce((maxRows, placement) => Math.max(maxRows, placement.y + placement.height), 0);
  return { placements, orderedPlacements, occupiedCells, rows };
}

export function reorderWidgetCollection(
  widgets: WidgetInstance[],
  draggedId: string,
  targetId: string | null,
): WidgetInstance[] {
  const next = [...widgets];
  const draggedIndex = next.findIndex((widget) => widget.id === draggedId);
  if (draggedIndex < 0) {
    return widgets;
  }
  const [dragged] = next.splice(draggedIndex, 1);
  if (targetId === null) {
    next.push(dragged);
    return next;
  }
  const targetIndex = next.findIndex((widget) => widget.id === targetId);
  if (targetIndex < 0) {
    next.push(dragged);
    return next;
  }
  next.splice(targetIndex, 0, dragged);
  return next;
}

export function findClosestWidgetId(
  placements: PackedPlacement[],
  pointer: { x: number; y: number },
  excludeWidgetId: string,
  cellWidth: number,
  rowHeight: number,
): string | null {
  let bestId: string | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;

  for (const placement of placements) {
    if (placement.widgetId === excludeWidgetId) {
      continue;
    }
    const centerX = placement.x * (cellWidth + BOARD_GAP_PX) + ((placement.width * cellWidth) + ((placement.width - 1) * BOARD_GAP_PX)) / 2;
    const centerY = placement.y * (rowHeight + BOARD_GAP_PX) + ((placement.height * rowHeight) + ((placement.height - 1) * BOARD_GAP_PX)) / 2;
    const distance = Math.hypot(pointer.x - centerX, pointer.y - centerY);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestId = placement.widgetId;
    }
  }

  return bestId;
}

function findSlot(occupancy: boolean[][], width: number, height: number) {
  let row = 0;
  while (true) {
    ensureRows(occupancy, row + height);
    for (let col = 0; col <= BOARD_COLUMNS - width; col += 1) {
      if (canPlace(occupancy, col, row, width, height)) {
        return { col, row };
      }
    }
    row += 1;
  }
}

function ensureRows(occupancy: boolean[][], rowCount: number) {
  while (occupancy.length < rowCount) {
    occupancy.push(Array.from({ length: BOARD_COLUMNS }, () => false));
  }
}

function canPlace(occupancy: boolean[][], col: number, row: number, width: number, height: number) {
  for (let dy = 0; dy < height; dy += 1) {
    for (let dx = 0; dx < width; dx += 1) {
      if (occupancy[row + dy]?.[col + dx]) {
        return false;
      }
    }
  }
  return true;
}

function markOccupied(occupancy: boolean[][], col: number, row: number, width: number, height: number) {
  for (let dy = 0; dy < height; dy += 1) {
    for (let dx = 0; dx < width; dx += 1) {
      occupancy[row + dy][col + dx] = true;
    }
  }
}
