"use client";

import { useEffect, useMemo, useState } from "react";

import { apiUrl, apiWebSocketUrl } from "@/lib/constants";
import type { WidgetRendererProps } from "@/lib/types";

type AgentStatus =
  | "created"
  | "queued"
  | "running"
  | "waiting_for_review"
  | "completed"
  | "failed"
  | "cancelled"
  | "paused";

interface AgentEntity {
  id: string;
  parent_id?: string | null;
  session_id: string;
  name: string;
  type: "session" | "task" | "subagent";
  source: string;
  status: AgentStatus;
  progress: number;
  updated_at: string;
  metadata?: Record<string, unknown>;
}

interface AgentTreeNode {
  agent: AgentEntity;
  children: AgentTreeNode[];
}

interface AgentTree {
  roots: AgentTreeNode[];
  total: number;
}

interface RuntimeEvent {
  id: string;
  type: string;
  level: string;
  message?: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

interface AgentSnapshot {
  tree: AgentTree;
  events: RuntimeEvent[];
}

const INITIAL_SNAPSHOT: AgentSnapshot = {
  tree: { roots: [], total: 0 },
  events: [],
};

export function AgentOverviewRenderer({ widget }: WidgetRendererProps) {
  const maxAgents = typeof widget.config.max_agents === "number" ? widget.config.max_agents : 6;
  const includeTimeline = widget.config.include_timeline !== false;
  const showCompleted = widget.config.show_completed === true;
  const scope = typeof widget.config.scope === "string" ? widget.config.scope : "all";
  const [snapshot, setSnapshot] = useState<AgentSnapshot>(INITIAL_SNAPSHOT);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [treeResponse, eventsResponse] = await Promise.all([
          fetch(apiUrl("/agents/tree"), { cache: "no-store" }),
          fetch(apiUrl("/agents/events?limit=20"), { cache: "no-store" }),
        ]);
        if (!treeResponse.ok || !eventsResponse.ok) {
          throw new Error("Agent runtime snapshot unavailable");
        }
        const [tree, events] = (await Promise.all([treeResponse.json(), eventsResponse.json()])) as [
          AgentTree,
          RuntimeEvent[],
        ];
        if (!cancelled) {
          setSnapshot({ tree, events });
          setError(null);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Agent runtime unavailable");
        }
      }
    };

    void load();
    const socket = new WebSocket(apiWebSocketUrl("/board/stream"));
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as { type: string; payload?: Record<string, unknown> };
        if (payload.type === "stream.reset") {
          void load();
          return;
        }
        if (payload.type.startsWith("agent.")) {
          void load();
        }
      } catch {
        return;
      }
    };

    return () => {
      cancelled = true;
      socket.close();
    };
  }, []);

  const visibleNodes = useMemo(() => {
    const flattened = flattenTree(snapshot.tree.roots, collapsed);
    return flattened
      .filter((item) => {
        if (!showCompleted && ["completed", "cancelled"].includes(item.agent.status)) {
          return false;
        }
        if (scope === "active") {
          return ["created", "queued", "running"].includes(item.agent.status);
        }
        if (scope === "review_required") {
          return item.agent.status === "waiting_for_review";
        }
        return true;
      })
      .slice(0, maxAgents);
  }, [collapsed, maxAgents, scope, showCompleted, snapshot.tree.roots]);

  const summary = useMemo(() => summarizeAgents(flattenTree(snapshot.tree.roots, {})), [snapshot.tree.roots]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden">
      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
        <Stat label="Active" value={summary.active} tone="accent" />
        <Stat label="Queued" value={summary.queued} tone="slate" />
        <Stat label="Review" value={summary.review} tone="warn" />
        <Stat label="Failed" value={summary.failed} tone="critical" />
      </div>

      {error ? (
        <div className="rounded-panel border border-critical/30 bg-critical/10 p-3 text-sm text-critical">{error}</div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-auto">
        {visibleNodes.length === 0 ? (
          <div className="flex h-full items-center justify-center p-6 text-sm text-slate-400">No agent activity</div>
        ) : (
          <div className="divide-y divide-edge">
            {visibleNodes.map(({ agent, depth, hasChildren }) => (
              <div
                key={agent.id}
                className="grid grid-cols-[minmax(0,1fr)_70px_44px] items-center gap-2 py-2 text-xs"
                style={{ paddingLeft: `${depth * 16}px` }}
              >
                <button
                  type="button"
                  disabled={!hasChildren}
                  onClick={() => setCollapsed((value) => ({ ...value, [agent.id]: !value[agent.id] }))}
                  className="min-w-0 text-left text-slate-100 disabled:cursor-default"
                >
                  <span className="mr-2 inline-block w-3 text-slate-500">{hasChildren ? (collapsed[agent.id] ? "+" : "-") : ""}</span>
                  <span className="truncate align-middle font-medium">{agent.name}</span>
                  <span className="ml-2 text-slate-500">{agent.type}</span>
                </button>
                <StatusText status={agent.status} />
                <span className="text-right text-slate-300">{agent.progress}%</span>
                <div className="col-span-3 h-1 overflow-hidden rounded-full bg-edge">
                  <div className={progressClass(agent.status)} style={{ width: `${agent.progress}%` }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {includeTimeline ? (
        <div className="shrink-0 border-t border-edge pt-2">
          {snapshot.events.length === 0 ? (
            <p className="px-1 text-xs text-slate-500">No recent agent events</p>
          ) : (
            <div className="max-h-24 divide-y divide-edge overflow-auto">
              {snapshot.events.slice(-5).map((event) => (
                <div key={event.id} className="flex items-center gap-2 py-1 text-xs">
                  <span className={event.level === "error" ? "text-critical" : event.level === "warning" ? "text-warn" : "text-accent"}>
                    {event.type}
                  </span>
                  <span className="min-w-0 truncate text-slate-400">{event.message ?? ""}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function flattenTree(roots: AgentTreeNode[], collapsed: Record<string, boolean>) {
  const rows: Array<{ agent: AgentEntity; depth: number; hasChildren: boolean }> = [];
  const visit = (node: AgentTreeNode, depth: number) => {
    rows.push({ agent: node.agent, depth, hasChildren: node.children.length > 0 });
    if (!collapsed[node.agent.id]) {
      node.children.forEach((child) => visit(child, depth + 1));
    }
  };
  roots.forEach((root) => visit(root, 0));
  return rows;
}

function summarizeAgents(rows: Array<{ agent: AgentEntity }>) {
  return rows.reduce(
    (summary, row) => {
      if (["created", "queued", "running"].includes(row.agent.status)) {
        summary.active += 1;
      }
      if (row.agent.status === "queued") {
        summary.queued += 1;
      }
      if (row.agent.status === "waiting_for_review") {
        summary.review += 1;
      }
      if (row.agent.status === "failed") {
        summary.failed += 1;
      }
      return summary;
    },
    { active: 0, queued: 0, review: 0, failed: 0 },
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: "accent" | "slate" | "warn" | "critical" }) {
  const valueClass = {
    accent: "text-accent",
    slate: "text-slate-100",
    warn: "text-warn",
    critical: "text-critical",
  }[tone];
  return (
    <div className="flex items-baseline gap-1.5">
      <span className={`text-lg font-semibold ${valueClass}`}>{value}</span>
      <span className="text-[10px] uppercase tracking-[0.12em] text-slate-400">{label}</span>
    </div>
  );
}

function StatusText({ status }: { status: AgentStatus }) {
  const className =
    status === "failed"
      ? "text-critical"
      : status === "waiting_for_review"
        ? "text-warn"
        : status === "running"
          ? "text-accent"
          : "text-slate-400";
  return <span className={`truncate text-center ${className}`}>{status.replaceAll("_", " ")}</span>;
}

function progressClass(status: AgentStatus) {
  const base = "h-full rounded-full transition-[width] duration-300 ";
  if (status === "failed") {
    return `${base}bg-critical/70`;
  }
  if (status === "waiting_for_review") {
    return `${base}bg-warn/70`;
  }
  return `${base}bg-accent/70`;
}
