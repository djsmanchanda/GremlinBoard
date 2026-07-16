import type { BoardPatch, BoardState, RuntimeEventMessage } from "@/lib/types";

export interface BoardProjectionState {
  board: BoardState | null;
  lastSequence: number;
  needsSnapshot: boolean;
  bootId: string | null;
}

export type BoardProjectionResult =
  | { kind: "applied"; state: BoardProjectionState }
  | { kind: "ignored"; state: BoardProjectionState }
  | { kind: "snapshot_required"; state: BoardProjectionState };

export function applyBoardEvent(
  state: BoardProjectionState,
  event: RuntimeEventMessage<BoardState | BoardPatch>,
): BoardProjectionResult {
  const sequence = typeof event.sequence === "number" ? event.sequence : state.lastSequence;
  if (state.lastSequence > 0 && sequence <= state.lastSequence) {
    return { kind: "ignored", state };
  }

  if (event.type === "stream.reset") {
    return {
      kind: "snapshot_required",
      state: { ...state, lastSequence: sequence, needsSnapshot: true },
    };
  }

  if (event.type === "board.snapshot" && isBoardState(event.payload)) {
    return {
      kind: "applied",
      state: {
        board: event.payload,
        lastSequence: sequence,
        needsSnapshot: false,
        bootId: event.payload.boot_id ?? state.bootId,
      },
    };
  }

  if (state.lastSequence > 0 && sequence > state.lastSequence + 1) {
    return {
      kind: "snapshot_required",
      state: { ...state, lastSequence: sequence, needsSnapshot: true },
    };
  }

  if (event.type === "board.patch" && isBoardPatch(event.payload)) {
    if (state.board === null || state.needsSnapshot) {
      return {
        kind: "snapshot_required",
        state: { ...state, lastSequence: sequence, needsSnapshot: true },
      };
    }
    return {
      kind: "applied",
      state: {
        board: applyBoardPatch(state.board, event.payload),
        lastSequence: sequence,
        needsSnapshot: false,
        bootId: state.bootId,
      },
    };
  }

  return { kind: "ignored", state: { ...state, lastSequence: sequence } };
}

export function applyBoardPatch(board: BoardState, patch: BoardPatch): BoardState {
  if (patch.board_id !== board.id) {
    return board;
  }

  const removed = new Set(patch.removed_widget_ids ?? []);
  const widgetsById = new Map(
    board.widgets.filter((widget) => !removed.has(widget.id)).map((widget) => [widget.id, widget]),
  );
  for (const widget of patch.upserted_widgets ?? []) {
    widgetsById.set(widget.id, widget);
  }

  let widgets = Array.from(widgetsById.values());
  const orderedIds = patch.ordered_widget_ids ?? [];
  if (orderedIds.length > 0) {
    const order = new Map(orderedIds.map((id, index) => [id, index]));
    widgets = widgets.sort((left, right) => {
      const leftOrder = order.get(left.id) ?? Number.MAX_SAFE_INTEGER;
      const rightOrder = order.get(right.id) ?? Number.MAX_SAFE_INTEGER;
      if (leftOrder !== rightOrder) {
        return leftOrder - rightOrder;
      }
      return left.position_index - right.position_index;
    });
  }

  return {
    ...board,
    name: patch.name ?? board.name,
    owner_user_id: patch.owner_user_id === undefined ? board.owner_user_id : patch.owner_user_id,
    widgets,
  };
}

function isBoardState(value: unknown): value is BoardState {
  return Boolean(
    value &&
      typeof value === "object" &&
      "id" in value &&
      "name" in value &&
      Array.isArray((value as BoardState).widgets),
  );
}

function isBoardPatch(value: unknown): value is BoardPatch {
  return Boolean(value && typeof value === "object" && typeof (value as BoardPatch).board_id === "string");
}
