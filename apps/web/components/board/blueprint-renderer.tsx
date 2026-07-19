"use client";

import { Fragment } from "react";

import {
  evaluateShowIf,
  isLayoutNode,
  parseBlueprint,
  resolveLayout,
  type BlueprintGap,
  type BlueprintNode,
  type LayoutNode,
} from "@/lib/blueprint";
import type { JsonObject, WidgetRendererProps } from "@/lib/types";
import {
  ActionButtonPrimitive,
  BadgeRowPrimitive,
  EmptyStatePrimitive,
  KeyValuePrimitive,
  ListPrimitive,
  ProgressPrimitive,
  SparklinePrimitive,
  StatPrimitive,
  TablePrimitive,
  TextPrimitive,
  TimerPrimitive,
} from "@/components/board/blueprint-primitives";

/**
 * Universal blueprint renderer (P2.2). Renders any valid `view.blueprint.json`
 * document against `widget.state` using design-system-native display and
 * action-button primitives.
 * De-carded aesthetic: dividers and spacing instead of nested bordered boxes.
 */

const GAP_CLASS: Record<BlueprintGap, string> = {
  none: "gap-0",
  sm: "gap-1.5",
  md: "gap-3",
};

const GRID_COLUMNS_CLASS: Record<number, string> = {
  2: "grid-cols-2",
  3: "grid-cols-3",
  4: "grid-cols-4",
};

function gapClass(gap: BlueprintGap | undefined, compact: boolean): string {
  return GAP_CLASS[gap ?? (compact ? "sm" : "md")] ?? GAP_CLASS.md;
}

interface BlueprintNodeViewProps {
  node: BlueprintNode;
  state: unknown;
  compact: boolean;
  widgetId: string;
  currentConfig: JsonObject;
  onUpdateConfig?: (config: JsonObject) => void | Promise<void>;
}

function LayoutContainer({
  node,
  state,
  compact,
  widgetId,
  currentConfig,
  onUpdateConfig,
}: Omit<BlueprintNodeViewProps, "node"> & { node: LayoutNode }) {
  const children = Array.isArray(node.children) ? node.children : [];
  const rendered = children.map((child, index) => (
    <Fragment key={index}>
      <BlueprintNodeView
        node={child}
        state={state}
        compact={compact}
        widgetId={widgetId}
        currentConfig={currentConfig}
        onUpdateConfig={onUpdateConfig}
      />
    </Fragment>
  ));

  switch (node.type) {
    case "row":
      return <div className={`flex min-w-0 items-start ${gapClass(node.gap, compact)}`}>{rendered}</div>;
    case "grid": {
      const columns = GRID_COLUMNS_CLASS[node.columns] ?? GRID_COLUMNS_CLASS[2];
      return <div className={`grid ${columns} ${gapClass(node.gap, compact)}`}>{rendered}</div>;
    }
    case "scroll":
      return (
        <div className={`flex min-h-0 flex-1 flex-col overflow-y-auto pr-1 ${gapClass(node.gap, compact)}`}>{rendered}</div>
      );
    case "stack":
    default:
      return <div className={`flex min-w-0 flex-col ${gapClass(node.gap, compact)}`}>{rendered}</div>;
  }
}

function BlueprintNodeView({
  node,
  state,
  compact,
  widgetId,
  currentConfig,
  onUpdateConfig,
}: BlueprintNodeViewProps) {
  if (!node || typeof node !== "object" || typeof node.type !== "string") {
    return null;
  }
  if (!evaluateShowIf(state, node.show_if)) {
    return null;
  }
  if (isLayoutNode(node)) {
    return (
      <LayoutContainer
        node={node}
        state={state}
        compact={compact}
        widgetId={widgetId}
        currentConfig={currentConfig}
        onUpdateConfig={onUpdateConfig}
      />
    );
  }

  switch (node.type) {
    case "stat":
      return <StatPrimitive node={node} state={state} compact={compact} />;
    case "text":
      return <TextPrimitive node={node} state={state} compact={compact} />;
    case "badge_row":
      return <BadgeRowPrimitive node={node} state={state} compact={compact} />;
    case "list":
      return <ListPrimitive node={node} state={state} compact={compact} />;
    case "table":
      return <TablePrimitive node={node} state={state} compact={compact} />;
    case "key_value":
      return <KeyValuePrimitive node={node} state={state} compact={compact} />;
    case "progress":
      return <ProgressPrimitive node={node} state={state} compact={compact} />;
    case "sparkline":
      return <SparklinePrimitive node={node} state={state} compact={compact} />;
    case "timer":
      return <TimerPrimitive node={node} state={state} compact={compact} />;
    case "empty_state":
      return <EmptyStatePrimitive node={node} state={state} compact={compact} />;
    case "action_button":
      return (
        <ActionButtonPrimitive
          node={node}
          state={state}
          compact={compact}
          widgetId={widgetId}
          currentConfig={currentConfig}
          onUpdateConfig={onUpdateConfig}
        />
      );
    default:
      // Unknown primitive from a newer contract version: skip, never crash.
      return null;
  }
}

function BlueprintFallback({ message }: { message: string }) {
  return (
    <div className="flex h-full min-h-0 items-center justify-center p-3 text-center">
      <p className="text-xs text-slate-500">{message}</p>
    </div>
  );
}

export function BlueprintRenderer({ widget, onUpdateConfig }: WidgetRendererProps) {
  const blueprint = parseBlueprint(widget.blueprint ?? null);
  if (!blueprint) {
    return <BlueprintFallback message="Widget view unavailable: invalid blueprint." />;
  }

  const layout = resolveLayout(blueprint, widget.size);
  if (!layout) {
    return <BlueprintFallback message="Widget view unavailable: no layout for this size." />;
  }

  const compact = layout.tier === "compact" || widget.size === "1x1";

  return (
    <div className={`flex h-full min-h-0 flex-col overflow-hidden ${compact ? "gap-1" : "gap-2"}`}>
      <BlueprintNodeView
        node={layout.node}
        state={widget.state}
        compact={compact}
        widgetId={widget.id}
        currentConfig={widget.config}
        onUpdateConfig={onUpdateConfig}
      />
    </div>
  );
}
