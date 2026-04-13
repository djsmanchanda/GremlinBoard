"use client";

import { create } from "zustand";

import type { BoardState, WidgetRegistryEntry } from "@/lib/types";

interface BoardStore {
  board: BoardState | null;
  registry: Record<string, WidgetRegistryEntry>;
  draggedId: string | null;
  commandOpen: boolean;
  error: string | null;
  setBoard: (board: BoardState) => void;
  setRegistry: (registry: Record<string, WidgetRegistryEntry>) => void;
  setDraggedId: (draggedId: string | null) => void;
  setCommandOpen: (commandOpen: boolean) => void;
  setError: (error: string | null) => void;
}

export const useBoardStore = create<BoardStore>((set) => ({
  board: null,
  registry: {},
  draggedId: null,
  commandOpen: false,
  error: null,
  setBoard: (board) => set({ board }),
  setRegistry: (registry) => set({ registry }),
  setDraggedId: (draggedId) => set({ draggedId }),
  setCommandOpen: (commandOpen) => set({ commandOpen }),
  setError: (error) => set({ error }),
}));
