import { expect, test, type Page } from "@playwright/test";

import { collectBadHttpResponses } from "../helpers/http";

const monitoringViewports = [
  { name: "960x1080", width: 960, height: 1080 },
  { name: "1280x720", width: 1280, height: 720 },
  { name: "1920x1080", width: 1920, height: 1080 },
  { name: "2560x1440", width: 2560, height: 1440 },
] as const;

const seededWidgetTitle = /Launch Countdown|Countdown Timer|Sports Pulse|News Radar|Trend Stack|Ops Pinboard|Personal Pinboard/;

for (const viewport of monitoringViewports) {
  test.describe(`monitoring station ${viewport.name}`, () => {
    test.use({ viewport });

    test("loads the board and filters Add Widget", async ({ page }) => {
      const badHttpResponses = collectBadHttpResponses(page);
      await mockBoardApi(page);

      await page.goto("/");

      await expect(page.getByRole("heading", { name: "GremlinBoard" })).toBeVisible();
      await expect(page.getByText(/Monitoring-station board/i)).toBeVisible();
      await expect(page.getByText("Live board")).toBeVisible();

      await expect(page.getByRole("button", { name: "View" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Wall" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Half" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Desk" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Stats" })).toBeVisible();
      await expect(page.getByText(/\d+\s+widgets/i).first()).toBeVisible();
      await expect(page.getByText(/\d+\s+cols/i)).toBeVisible();

      await expect(page.getByRole("heading").filter({ hasText: seededWidgetTitle }).first()).toBeVisible();
      await expect(page.getByText(/\d+ restarts/)).toHaveCount(0);

      const alertDetails = page.getByRole("button", { name: "critical alert details" });
      await expect(alertDetails).toBeVisible();
      await expect(page.getByText("Restart spike", { exact: true })).toHaveCount(0);
      await alertDetails.click();
      await expect(alertDetails.getByText(/Restart spike/)).toBeVisible();

      const completedDetails = page.getByRole("button", { name: "completed alert details" });
      await expect(completedDetails).toBeVisible();
      await completedDetails.click();
      await expect(completedDetails.getByText("Completed successfully", { exact: true })).toBeVisible();

      await page.getByRole("button", { name: "Stats" }).click();
      await expect(page.getByText(/\d+ restarts/)).toHaveCount(2);

      await page.getByRole("button", { name: "Add widget" }).click();

      const dialog = page.getByRole("dialog", { name: "Add registered widget" });
      await expect(dialog).toBeVisible();

      const search = dialog.getByLabel("Search widgets");
      await expect(search).toBeFocused();

      await search.fill("pinboard");
      await expect(dialog.getByRole("button", { name: /Ops Pinboard|Personal Pinboard/i })).toBeVisible();
      await expect(dialog.getByRole("button", { name: /Sports Pulse/i })).toHaveCount(0);

      await search.fill("definitely-not-a-widget");
      await expect(dialog.getByText("No preset matched that search.")).toBeVisible();

      await dialog.getByRole("button", { name: "Close" }).click();
      await expect(dialog).toBeHidden();

      expect(badHttpResponses.all(), badHttpResponses.summary()).toEqual([]);
    });
  });
}

async function mockBoardApi(page: Page) {
  await page.routeWebSocket("**/api/board/stream*", (socket) => {
    socket.send(JSON.stringify({ type: "board.snapshot", sequence: 1, payload: mockBoard }));
  });
  await page.route("**/api/board", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockBoard),
    }),
  );
  await page.route("**/api/registry/widgets", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockRegistry),
    }),
  );
  await page.route("**/api/board/widgets/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockBoard),
    }),
  );
}

const countdownManifest = {
  id: "countdown",
  version: "1.0.0",
  name: "Countdown Timer",
  category: "utility",
  description: "Dense countdown tile for release windows, sessions, and deadlines.",
  min_size: "1x1",
  preferred_size: "1x2",
  allowed_sizes: ["1x1", "1x2", "2x2"],
  refresh_policy: { mode: "live", interval_seconds: 1 },
  lifecycle_policy: { stateful: true, expires: true, default_ttl_seconds: null },
  runtime_policy: {
    start_timeout_seconds: 5,
    refresh_timeout_seconds: 5,
    heartbeat_timeout_seconds: 30,
    max_retries: 2,
    retry_backoff_seconds: 1,
    stale_after_seconds: 60,
  },
  permissions: [],
  renderer: { target: "react", module: "@widgets/countdown/renderer", export_name: "CountdownRenderer" },
};

const sportsManifest = {
  id: "sports",
  version: "1.0.0",
  name: "Sports Pulse",
  category: "monitoring",
  description: "Live sports scores and fixtures.",
  min_size: "2x2",
  preferred_size: "2x2",
  allowed_sizes: ["2x2", "4x2"],
  refresh_policy: { mode: "interval", interval_seconds: 120 },
  lifecycle_policy: { stateful: true, expires: false, default_ttl_seconds: null },
  runtime_policy: {
    start_timeout_seconds: 5,
    refresh_timeout_seconds: 8,
    heartbeat_timeout_seconds: 60,
    max_retries: 2,
    retry_backoff_seconds: 2,
    stale_after_seconds: 300,
  },
  permissions: ["network"],
  renderer: { target: "react", module: "@widgets/sports/renderer", export_name: "SportsRenderer" },
};

const pinboardManifest = {
  id: "pinboard",
  version: "1.0.0",
  name: "Personal Pinboard",
  category: "personal",
  description: "Compact personal notes and pinned reminders that persist until removed.",
  min_size: "2x2",
  preferred_size: "2x4",
  allowed_sizes: ["2x2", "2x4", "4x4"],
  refresh_policy: { mode: "manual", interval_seconds: 0 },
  lifecycle_policy: { stateful: true, expires: false, default_ttl_seconds: null },
  runtime_policy: {
    start_timeout_seconds: 5,
    refresh_timeout_seconds: 5,
    heartbeat_timeout_seconds: 300,
    max_retries: 1,
    retry_backoff_seconds: 1,
    stale_after_seconds: 600,
  },
  permissions: [],
  renderer: { target: "react", module: "@widgets/pinboard/renderer", export_name: "PinboardRenderer" },
};

const mockRegistry = {
  countdown: {
    manifest: countdownManifest,
    config_schema: {
      type: "object",
      properties: {
        timers: {
          type: "array",
          title: "Timers",
          maxItems: 4,
          items: {
            type: "object",
            properties: {
              id: { type: "string", title: "ID" },
              label: { type: "string", title: "Label" },
              target_time: { type: "string", title: "Target time", format: "date-time" },
              duration_seconds: { type: "integer", title: "Restart duration", minimum: 1, default: 3600 },
            },
          },
        },
      },
    },
    plugin: { widget_id: "countdown", version: "1.0.0", enabled: true, installed: true, is_core: true, source_type: "core" },
  },
  sports: {
    manifest: sportsManifest,
    config_schema: { type: "object", properties: { league: { type: "string", title: "League", default: "NBA" } } },
    plugin: { widget_id: "sports", version: "1.0.0", enabled: true, installed: true, is_core: true, source_type: "core" },
  },
  pinboard: {
    manifest: pinboardManifest,
    config_schema: { type: "object", properties: { notes: { type: "array", title: "Notes", default: [] } } },
    plugin: { widget_id: "pinboard", version: "1.0.0", enabled: true, installed: true, is_core: true, source_type: "core" },
  },
};

const mockBoard = {
  id: "monitor-board",
  name: "Monitoring station",
  widgets: [
    {
      id: "widget-countdown",
      board_id: "monitor-board",
      widget_id: "countdown",
      title: "Launch Countdown",
      size: "2x2",
      position_index: 0,
      config: {
        timers: [
          {
            id: "cutover",
            label: "Cutover",
            target_time: new Date(Date.now() + 15 * 60_000).toISOString(),
            duration_seconds: 900,
          },
        ],
      },
      state: { meta: { providers: [{ provider_id: "runtime", label: "Runtime", status: "degraded", error: null }] } },
      lifecycle_state: "running",
      status_message: "Runtime degraded by mock provider.",
      freshness_at: new Date(Date.now() - 10 * 60_000).toISOString(),
      expires_at: null,
      last_error: null,
      last_heartbeat: new Date().toISOString(),
      service_started_at: new Date(Date.now() - 60 * 60_000).toISOString(),
      service_uptime_seconds: 3600,
      restart_count: 6,
      consecutive_failures: 0,
    },
    {
      id: "widget-countdown-complete",
      board_id: "monitor-board",
      widget_id: "countdown",
      title: "Completed Countdown",
      size: "2x2",
      position_index: 1,
      config: {
        timers: [
          {
            id: "done",
            label: "Done",
            target_time: new Date(Date.now() - 60_000).toISOString(),
            duration_seconds: 60,
          },
        ],
      },
      state: { complete: true },
      lifecycle_state: "running",
      status_message: "complete",
      freshness_at: new Date().toISOString(),
      expires_at: null,
      last_error: null,
      last_heartbeat: new Date().toISOString(),
      service_started_at: new Date(Date.now() - 60 * 60_000).toISOString(),
      service_uptime_seconds: 3600,
      restart_count: 0,
      consecutive_failures: 0,
    },
  ],
};
