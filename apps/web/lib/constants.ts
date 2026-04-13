import type { TileSize } from "@/lib/types";

export const TILE_SIZE_STYLES: Record<TileSize, { colSpan: string; rowSpan: string }> = {
  "1x1": { colSpan: "md:col-span-1", rowSpan: "md:row-span-1" },
  "1x2": { colSpan: "md:col-span-1", rowSpan: "md:row-span-2" },
  "2x2": { colSpan: "md:col-span-2", rowSpan: "md:row-span-2" },
  "4x2": { colSpan: "md:col-span-4", rowSpan: "md:row-span-2" },
  "2x4": { colSpan: "md:col-span-2", rowSpan: "md:row-span-4" },
  "4x4": { colSpan: "md:col-span-4", rowSpan: "md:row-span-4" },
};

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_GREMLINBOARD_API_URL ?? "http://127.0.0.1:8000/api";
