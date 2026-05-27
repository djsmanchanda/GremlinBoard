"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { fetchRuntimeDevtoolsSnapshot, runDevtoolsAction } from "@/lib/api";
import { apiWebSocketUrl } from "@/lib/constants";
import type { JsonObject, RuntimeDevtoolsSnapshot, RuntimeEventMessage } from "@/lib/types";

type ConnectionState = "idle" | "connecting" | "open" | "closed" | "error";

interface StreamEventRecord {
  receivedAt: string;
  sequence: number;
  type: string;
  category: string;
  level: string;
  persistence: string;
  replayable: boolean;
  correlationId?: string | null;
  causationId?: string | null;
  payloadPreview: string;
}

const maxStreamEvents = 160;

export function RuntimeDevtoolsShell() {
  const [snapshot, setSnapshot] = useState<RuntimeDevtoolsSnapshot | null>(null);
  const [events, setEvents] = useState<StreamEventRecord[]>([]);
  const [connectionState, setConnectionState] = useState<ConnectionState>("idle");
  const [paused, setPaused] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [levelFilter, setLevelFilter] = useState("all");
  const [replayableOnly, setReplayableOnly] = useState(false);
  const [persistentOnly, setPersistentOnly] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState<StreamEventRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const lastSequenceRef = useRef(0);
  const reconnectTimer = useRef<number | null>(null);
  const pausedRef = useRef(paused);

  const loadSnapshot = () => {
    void fetchRuntimeDevtoolsSnapshot()
      .then((next) => {
        setSnapshot(next);
        setError(null);
      })
      .catch((requestError) => {
        setError(requestError instanceof Error ? requestError.message : "Failed to load runtime devtools snapshot");
      });
  };

  useEffect(() => {
    loadSnapshot();
  }, []);

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (document.visibilityState === "hidden") {
        return;
      }
      loadSnapshot();
    }, Math.max(snapshot?.runtime.monitor_cadence_seconds ?? 30, 15) * 1000);
    return () => window.clearInterval(interval);
  }, [snapshot?.runtime.monitor_cadence_seconds]);

  useEffect(() => {
    let websocket: WebSocket | null = null;
    let closed = false;
    let reconnectAttempt = 0;

    const scheduleReconnect = (connect: () => void) => {
      if (closed || document.visibilityState === "hidden" || reconnectTimer.current !== null) {
        return;
      }
      const delay = Math.min(30000, 1000 * 2 ** reconnectAttempt);
      reconnectAttempt += 1;
      reconnectTimer.current = window.setTimeout(() => {
        reconnectTimer.current = null;
        connect();
      }, delay);
    };

    const connect = () => {
      if (closed || document.visibilityState === "hidden") {
        return;
      }
      if (websocket && websocket.readyState !== WebSocket.CLOSED) {
        return;
      }
      setConnectionState("connecting");
      const lastSequence = lastSequenceRef.current;
      const suffix = lastSequence > 0 ? `?last_seq=${lastSequence}` : "";
      const nextSocket = new WebSocket(apiWebSocketUrl(`/board/stream${suffix}`));
      websocket = nextSocket;
      nextSocket.onopen = () => {
        reconnectAttempt = 0;
        setConnectionState("open");
      };
      nextSocket.onerror = () => setConnectionState("error");
      nextSocket.onclose = () => {
        if (websocket === nextSocket) {
          websocket = null;
        }
        setConnectionState("closed");
        scheduleReconnect(connect);
      };
      nextSocket.onmessage = (message) => {
        if (pausedRef.current) {
          return;
        }
        try {
          const parsed = JSON.parse(message.data as string) as RuntimeEventMessage<JsonObject>;
          const sequence = typeof parsed.sequence === "number" ? parsed.sequence : lastSequenceRef.current;
          lastSequenceRef.current = Math.max(lastSequenceRef.current, sequence);
          reconnectAttempt = 0;
          const record: StreamEventRecord = {
            receivedAt: new Date().toISOString(),
            sequence,
            type: parsed.type,
            category: parsed.category ?? parsed.type.split(".", 1)[0] ?? "unknown",
            level: parsed.level ?? "info",
            persistence: parsed.persistence ?? "ephemeral",
            replayable: parsed.replayable ?? true,
            correlationId: parsed.correlation_id,
            causationId: parsed.causation_id,
            payloadPreview: previewPayload(parsed.payload),
          };
          setEvents((items) => [record, ...items].slice(0, maxStreamEvents));
        } catch (parseError) {
          setError(parseError instanceof Error ? parseError.message : "Failed to parse stream event");
        }
      };
    };

    connect();
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        websocket?.close();
        return;
      }
      connect();
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      closed = true;
      if (reconnectTimer.current !== null) {
        window.clearTimeout(reconnectTimer.current);
      }
      websocket?.close();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  const filteredEvents = useMemo(
    () =>
      events.filter((event) => {
        if (categoryFilter !== "all" && event.category !== categoryFilter) {
          return false;
        }
        if (levelFilter !== "all" && event.level !== levelFilter) {
          return false;
        }
        if (replayableOnly && !event.replayable) {
          return false;
        }
        if (persistentOnly && event.persistence === "ephemeral") {
          return false;
        }
        return true;
      }),
    [categoryFilter, events, levelFilter, persistentOnly, replayableOnly],
  );
  const categories = useMemo(() => Array.from(new Set(events.map((event) => event.category))).sort(), [events]);
  const levels = useMemo(() => Array.from(new Set(events.map((event) => event.level))).sort(), [events]);

  const invokeAction = (action: "clear-replay" | "force-snapshot" | "simulate-stream-reset") => {
    setActionMessage(null);
    void runDevtoolsAction(action)
      .then((response) => {
        setActionMessage(`${response.action}: ${JSON.stringify(response.detail)}`);
        loadSnapshot();
      })
      .catch((requestError) => {
        setError(requestError instanceof Error ? requestError.message : "Devtools action failed");
      });
  };

  return (
    <main className="min-h-screen bg-[#05070a] px-4 py-5 text-slate-100 md:px-6">
      <section className="mx-auto max-w-7xl">
        <header className="mb-4 flex flex-col gap-4 border-b border-white/10 pb-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">Runtime devtools</div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-white">Runtime Inspector</h1>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link className="rounded border border-white/10 px-3 py-2 text-sm text-slate-200 hover:bg-white/[0.06]" href="/system">
              System
            </Link>
            <Link className="rounded border border-white/10 px-3 py-2 text-sm text-slate-200 hover:bg-white/[0.06]" href="/">
              Board
            </Link>
            <button className="rounded border border-white/10 px-3 py-2 text-sm hover:bg-white/[0.06]" onClick={loadSnapshot}>
              Refresh snapshot
            </button>
          </div>
        </header>

        {error ? <StatusNotice tone="error" text={error} /> : null}
        {actionMessage ? <StatusNotice tone="info" text={actionMessage} /> : null}

        <section className="grid gap-3 md:grid-cols-4">
          <MetricTile label="Runtime" value={snapshot?.runtime.state ?? "unknown"} detail={`presence ${snapshot?.runtime.presence?.state ?? "unknown"}`} />
          <MetricTile label="Stream" value={connectionState} detail={`last seq ${lastSequenceRef.current || snapshot?.runtime.latest_sequence || 0}`} />
          <MetricTile label="Queue" value={snapshot?.queues.health ?? "unknown"} detail={`depth ${snapshot?.queues.event_bus_queue_depth ?? 0}`} />
          <MetricTile label="Replay" value={`${snapshot?.replay.history_size ?? 0}`} detail={`miss ${snapshot?.replay.replay_miss_count ?? 0} reset ${snapshot?.replay.stream_reset_count ?? 0}`} />
        </section>

        <section className="mt-4 grid gap-4 xl:grid-cols-[1.45fr_0.85fr]">
          <div className="border border-white/10 bg-[#080b0f]">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
              <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">Event Stream</h2>
              <div className="flex flex-wrap gap-2">
                <select className="control-select" value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
                  <option value="all">all categories</option>
                  {categories.map((category) => <option key={category} value={category}>{category}</option>)}
                </select>
                <select className="control-select" value={levelFilter} onChange={(event) => setLevelFilter(event.target.value)}>
                  <option value="all">all levels</option>
                  {levels.map((level) => <option key={level} value={level}>{level}</option>)}
                </select>
                <label className="control-check"><input type="checkbox" checked={replayableOnly} onChange={(event) => setReplayableOnly(event.target.checked)} /> replayable</label>
                <label className="control-check"><input type="checkbox" checked={persistentOnly} onChange={(event) => setPersistentOnly(event.target.checked)} /> persisted</label>
                <button className="control-button" onClick={() => setPaused((value) => !value)}>{paused ? "Resume" : "Pause"}</button>
              </div>
            </div>
            <div className="max-h-[520px] overflow-auto">
              <table className="min-w-full text-left text-xs">
                <thead className="sticky top-0 bg-[#080b0f] text-[10px] uppercase tracking-[0.14em] text-slate-500">
                  <tr>
                    <th className="px-3 py-2">Seq</th>
                    <th className="px-3 py-2">Type</th>
                    <th className="px-3 py-2">Category</th>
                    <th className="px-3 py-2">Level</th>
                    <th className="px-3 py-2">Persistence</th>
                    <th className="px-3 py-2">Payload</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredEvents.map((event) => (
                    <tr key={`${event.sequence}-${event.receivedAt}`} className="border-t border-white/5 hover:bg-white/[0.03]" onClick={() => setSelectedEvent(event)}>
                      <td className="px-3 py-2 font-mono text-slate-300">{event.sequence}</td>
                      <td className="px-3 py-2 font-mono text-cyan-100">{event.type}</td>
                      <td className="px-3 py-2">{event.category}</td>
                      <td className="px-3 py-2">{event.level}</td>
                      <td className="px-3 py-2">{event.persistence}</td>
                      <td className="max-w-[260px] truncate px-3 py-2 text-slate-400">{event.payloadPreview}</td>
                    </tr>
                  ))}
                  {filteredEvents.length === 0 ? (
                    <tr><td className="px-3 py-8 text-center text-slate-500" colSpan={6}>No matching stream events.</td></tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>

          <aside className="space-y-4">
            <Panel title="Replay + Websocket">
              <KeyValue label="Subscribers" value={String(snapshot?.websocket.subscriber_count ?? 0)} />
              <KeyValue label="Oldest replay seq" value={String(snapshot?.replay.replay_oldest_sequence ?? "none")} />
              <KeyValue label="Replay miss reasons" value={formatReasonCounts(snapshot?.replay.replay_miss_reasons)} />
              <KeyValue label="Snapshot fallbacks" value={String(snapshot?.websocket.snapshot_fallback_count ?? 0)} />
              <KeyValue label="Stream resets" value={String(snapshot?.websocket.stream_reset_count ?? 0)} />
              <div className="mt-3 space-y-2">
                {snapshot?.websocket.subscribers.map((subscriber) => (
                  <div key={subscriber.id} className="border border-white/10 px-3 py-2">
                    <div className="flex justify-between text-xs"><span>subscriber {subscriber.id}</span><span>{subscriber.health}</span></div>
                    <div className="mt-1 text-[11px] text-slate-500">
                      queue {subscriber.queue_depth}/{subscriber.max_queue_size} drops {subscriber.dropped_events} resets {subscriber.stream_reset_count}
                    </div>
                    <div className="mt-1 text-[11px] text-slate-600">overflow {formatTimestamp(subscriber.last_overflow_at)}</div>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="Queue Pressure">
              <KeyValue label="Event bus depth" value={String(snapshot?.queues.event_bus_queue_depth ?? 0)} />
              <KeyValue label="Websocket depth" value={String(snapshot?.queues.websocket_queue_depth ?? 0)} />
              <KeyValue label="Internal depth" value={String(snapshot?.queues.internal_queue_depth ?? 0)} />
              <KeyValue label="Generation depth" value={String(snapshot?.queues.generation_queue_depth ?? 0)} />
              <KeyValue label="Dropped events" value={String(snapshot?.queues.dropped_event_count ?? 0)} />
              <KeyValue label="Stale subscribers" value={String(snapshot?.queues.stale_subscriber_count ?? 0)} />
              <KeyValue label="Pruned subscribers" value={String(snapshot?.queues.pruned_subscriber_count ?? 0)} />
            </Panel>

            <Panel title="Provider Activity">
              <KeyValue label="Cache entries" value={`${snapshot?.providers.cache.entry_count ?? 0}/${snapshot?.providers.cache.max_entries ?? 0}`} />
              <KeyValue label="Expired cache" value={String(snapshot?.providers.cache.expired_entry_count ?? 0)} />
              <KeyValue label="Stale retention" value={`${snapshot?.providers.cache.stale_retention_seconds ?? 0}s`} />
              <KeyValue label="In-flight requests" value={`${snapshot?.providers.coordination.inflight_request_count ?? 0}/${snapshot?.providers.coordination.max_inflight_requests ?? 0}`} />
              <KeyValue label="Coalesced waiters" value={String(snapshot?.providers.coordination.coalesced_request_count ?? 0)} />
              <KeyValue label="Degraded providers" value={String(snapshot?.providers.degradation.length ?? 0)} />
              <div className="mt-3 space-y-2">
                {snapshot?.providers.providers.map((provider) => (
                  <div key={provider.provider_id} className="border border-white/10 px-3 py-2 text-xs">
                    <div className="flex justify-between"><span className="font-mono text-cyan-100">{provider.provider_id}</span><span>{provider.last_status}</span></div>
                    <div className="mt-1 text-slate-500">
                      active {provider.active_requests} total {provider.total_requests} coalesced {provider.coalesced_requests} hits {provider.cache_hits} misses {provider.cache_misses} errors {provider.errors}
                    </div>
                    <div className="mt-1 text-slate-600">
                      failures {provider.consecutive_failures} cooldown skips {provider.cooldown_skips} until {formatTimestamp(provider.cooldown_until)}
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          </aside>
        </section>

        <section className="mt-4 grid gap-4 lg:grid-cols-2">
          <Panel title="Recent Replay Buffer">
            <div className="max-h-72 overflow-auto">
              {(snapshot?.replay.recent_events ?? []).map((event) => (
                <div key={event.id} className="grid grid-cols-[70px_1fr_auto] gap-2 border-b border-white/5 py-2 text-xs">
                  <span className="font-mono text-slate-500">{event.sequence}</span>
                  <span className="font-mono text-slate-200">{event.type}</span>
                  <span className="text-slate-500">{event.payload_size}b</span>
                </div>
              ))}
            </div>
          </Panel>
          <Panel title="Operator Actions">
            <div className="flex flex-wrap gap-2">
              <button className="control-button" onClick={() => invokeAction("force-snapshot")}>Force snapshot</button>
              <button className="control-button" onClick={() => invokeAction("simulate-stream-reset")}>Simulate stream.reset</button>
              <button className="control-button border-amber-300/30 text-amber-100" onClick={() => invokeAction("clear-replay")}>Clear replay buffer</button>
            </div>
            {selectedEvent ? (
              <pre className="mt-4 max-h-44 overflow-auto bg-black/30 p-3 text-xs text-slate-300">{JSON.stringify(selectedEvent, null, 2)}</pre>
            ) : (
              <p className="mt-4 text-sm text-slate-500">Select a stream event to inspect its local record.</p>
            )}
          </Panel>
        </section>
      </section>
    </main>
  );
}

function MetricTile({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="border border-white/10 bg-[#080b0f] px-4 py-3">
      <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className="mt-2 text-xl font-semibold text-white">{value}</div>
      <div className="mt-1 text-xs text-slate-500">{detail}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border border-white/10 bg-[#080b0f] p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">{title}</h2>
      {children}
    </section>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-white/5 py-1.5 text-xs">
      <span className="text-slate-500">{label}</span>
      <span className="font-mono text-slate-200">{value}</span>
    </div>
  );
}

function StatusNotice({ tone, text }: { tone: "error" | "info"; text: string }) {
  const cls = tone === "error" ? "border-rose-300/25 bg-rose-300/10 text-rose-100" : "border-cyan-300/20 bg-cyan-300/10 text-cyan-100";
  return <div className={`mb-4 border px-4 py-3 text-sm ${cls}`}>{text}</div>;
}

function previewPayload(payload: unknown): string {
  if (payload == null) {
    return "";
  }
  try {
    const text = JSON.stringify(payload);
    return text.length > 180 ? `${text.slice(0, 180)}...` : text;
  } catch {
    return String(payload);
  }
}

function formatReasonCounts(reasons?: Record<string, number>): string {
  const entries = Object.entries(reasons ?? {});
  if (entries.length === 0) {
    return "none";
  }
  return entries.map(([reason, count]) => `${reason}:${count}`).join(" ");
}

function formatTimestamp(value?: string | null): string {
  if (!value) {
    return "none";
  }
  return value;
}
