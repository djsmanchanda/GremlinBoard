import { expect, test, type Page } from "@playwright/test";

import { collectBadHttpResponses } from "../helpers/http";

test("renders runtime devtools snapshot and websocket stream", async ({ page }) => {
  const badHttpResponses = collectBadHttpResponses(page);
  await mockDevtoolsApi(page);

  await page.goto("/system/devtools");

  await expect(page.getByRole("heading", { name: "Runtime Inspector" })).toBeVisible();
  await expect(page.getByText("Event Stream")).toBeVisible();
  await expect(page.getByText("Replay + Websocket")).toBeVisible();
  await expect(page.getByText("Queue Pressure")).toBeVisible();
  await expect(page.getByText("Provider Activity")).toBeVisible();
  await expect(page.getByRole("button", { name: "Force snapshot" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Simulate stream.reset" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Clear replay buffer" })).toBeVisible();

  expect(badHttpResponses.all(), badHttpResponses.summary()).toEqual([]);
});

async function mockDevtoolsApi(page: Page) {
  await page.routeWebSocket("**/api/board/stream*", (socket) => {
    socket.send(
      JSON.stringify({
        type: "board.patch",
        id: "event-live",
        sequence: 45,
        category: "board",
        level: "info",
        persistence: "ephemeral",
        replayable: true,
        correlation_id: "corr-live",
        payload: { board_id: "monitor-board", upserted_widgets: [], removed_widget_ids: [] },
      }),
    );
  });
  await page.route(/\/api\/devtools\/snapshot(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockDevtoolsSnapshot),
    }),
  );
  await page.route(/\/api\/devtools\/actions\/.+$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok", action: "force-snapshot", detail: { published: true } }),
    }),
  );
}

const mockDevtoolsSnapshot = {
  observed_at: new Date().toISOString(),
  runtime: {
    state: "active",
    presence: {
      state: "active",
      active_sources: [{ source: "system_panel", active: 1, last_seen_at: new Date().toISOString() }],
      active_websocket_count: 1,
      recent_interaction_at: new Date().toISOString(),
      idle_after_seconds: 90,
      suspended: false,
      degraded: false,
      reason: null,
      updated_at: new Date().toISOString(),
    },
    active_runners: 2,
    websocket_subscribers: 1,
    monitor_cadence_seconds: 30,
    provider_degradation: [],
    queue_depth: 1,
    dropped_event_count: 0,
    replay_event_count: 3,
    published_event_count: 44,
    replay_history_size: 12,
    replay_oldest_sequence: 33,
    latest_sequence: 44,
    stream_reset_count: 1,
    replay_miss_count: 0,
    replay_miss_reasons: {},
    snapshot_fallback_count: 1,
    websocket_queue_depth: 0,
    internal_queue_depth: 1,
    max_subscriber_queue_depth: 1,
    websocket_dropped_event_count: 0,
    stale_subscriber_count: 0,
    pruned_subscriber_count: 0,
    observability_sink_error: null,
    registry_size: 6,
    widgets_total: 5,
    active_agents: 1,
    agents_waiting_for_review: 0,
    agents_failed: 0,
    runners: [],
    startup_recovery: {
      recovered_widgets: 5,
      skipped_widgets: 0,
      orphan_widgets: 0,
      registry_size: 6,
      checked_at: new Date().toISOString(),
    },
  },
  replay: {
    history_size: 12,
    replay_oldest_sequence: 33,
    latest_sequence: 44,
    replay_event_count: 3,
    replay_miss_count: 0,
    replay_miss_reasons: {},
    stream_reset_count: 1,
    snapshot_fallback_count: 1,
    recent_events: [
      {
        id: "event-44",
        sequence: 44,
        type: "runtime.devtools_probe",
        category: "runtime",
        level: "info",
        visibility: "both",
        persistence: "ephemeral",
        replayable: true,
        source: { component: "test" },
        correlation_id: "corr-1",
        causation_id: null,
        created_at: new Date().toISOString(),
        payload_keys: ["detail"],
        payload_size: 20,
      },
    ],
  },
  websocket: {
    subscriber_count: 1,
    subscribers: [
      {
        id: "1",
        kind: "websocket",
        queue_depth: 0,
        max_queue_size: 64,
        dropped_events: 0,
        stream_reset_count: 1,
        created_at: new Date().toISOString(),
        categories: [],
        event_types: [],
        health: "ok",
      },
    ],
    stream_reset_count: 1,
    replay_miss_count: 0,
    snapshot_fallback_count: 1,
  },
  queues: {
    event_bus_queue_depth: 1,
    websocket_queue_depth: 0,
    internal_queue_depth: 1,
    generation_queue_depth: 0,
    generation_queued_input_count: 0,
    generation_worker_running: true,
    max_subscriber_queue_depth: 1,
    dropped_event_count: 0,
    websocket_dropped_event_count: 0,
    stale_subscriber_count: 0,
    pruned_subscriber_count: 0,
    observability_sink_error: null,
    health: "ok",
    durability_notes: { ephemeral: "May drop.", timeline: "Persisted.", state: "Committed state signal." },
  },
  providers: {
    providers: [
      {
        provider_id: "newsapi",
        active_requests: 0,
        total_requests: 8,
        coalesced_requests: 1,
        cooldown_skips: 0,
        cache_hits: 4,
        cache_misses: 4,
        stale_fallbacks: 1,
        fallback_responses: 0,
        errors: 1,
        last_status: "healthy",
        last_error: null,
        last_started_at: new Date().toISOString(),
        last_finished_at: new Date().toISOString(),
        consecutive_failures: 0,
        cooldown_until: null,
      },
    ],
    coordination: {
      inflight_request_count: 0,
      max_inflight_requests: 64,
      inflight_keys: [],
      oldest_inflight_started_at: null,
      coalesced_request_count: 1,
    },
    cache: {
      entry_count: 3,
      max_entries: 256,
      expired_entry_count: 0,
      stale_retention_seconds: 600,
      namespace_counts: { news: 2, sports: 1 },
    },
    degradation: [],
  },
  pressure: {
    queue_health: "ok",
    replay_pressure: "ok",
    subscriber_pressure: "ok",
    provider_pressure: "ok",
    stale_widget_count: 0,
    error_widget_count: 0,
  },
};
