import type { TileSize } from "@/lib/types";

export type WidgetDisplayTier = "compact" | "standard" | "expanded";

export function getWidgetDisplayTier(size: TileSize): WidgetDisplayTier {
  if (size === "1x1") {
    return "compact";
  }
  if (size === "4x4" || size === "2x4") {
    return "expanded";
  }
  return "standard";
}

export function isCompactWidget(size: TileSize) {
  return size === "1x1";
}

export function isSmallWidget(size: TileSize) {
  return size === "1x1" || size === "1x2";
}
