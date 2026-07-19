import { expect, test, type Page } from "@playwright/test";

import { collectBadHttpResponses } from "../helpers/http";

test.describe("blueprint widget", () => {
  test.use({ viewport: { width: 1280, height: 720 } });

  test("renders a blueprint-kind widget from state bindings", async ({ page }) => {
    const badHttpResponses = collectBadHttpResponses(page);
    await mockBoardApi(page);

    await page.goto("/");

    const card = page.getByRole("heading", { name: "Deploy Monitor" }).locator("..").locator("../../..");
    await expect(page.getByRole("heading", { name: "Deploy Monitor" })).toBeVisible();

    // Stat primitive: bound value renders.
    await expect(page.getByText("Success rate", { exact: true })).toBeVisible();
    await expect(page.getByText("87", { exact: true })).toBeVisible();

    // Stat with an unresolvable path degrades to an em-dash instead of crashing.
    await expect(page.getByText("Missing metric", { exact: true })).toBeVisible();
    await expect(page.getByText("—", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("undefined", { exact: true })).toHaveCount(0);

    // List primitive: rows from items_path, honoring limit (2 of 3).
    await expect(page.getByText("api rollout", { exact: true })).toBeVisible();
    await expect(page.getByText("web rollout", { exact: true })).toBeVisible();
    await expect(page.getByText("worker rollout", { exact: true })).toHaveCount(0);
    const headlineLink = page.getByRole("link", { name: /api rollout/ });
    await expect(headlineLink).toHaveAttribute("href", "https://example.com/deployments/api");
    await expect(headlineLink).toHaveAttribute("target", "_blank");
    await expect(headlineLink).toHaveAttribute("rel", "noopener noreferrer");

    // Progress primitive renders its label and percentage.
    await expect(page.getByText("Rollout", { exact: true })).toBeVisible();
    await expect(page.getByText("64%", { exact: true })).toBeVisible();

    // show_if: guard path is absent from state, so this node is skipped.
    await expect(page.getByText("Degraded mode", { exact: true })).toHaveCount(0);

    // The renderer-unavailable fallback must not appear for blueprint widgets.
    await expect(page.getByText("Renderer unavailable")).toHaveCount(0);

    const refreshRequestPromise = page.waitForRequest(
      (request) => request.method() === "POST" && request.url().endsWith("/api/board/widgets/widget-deploy-monitor/refresh"),
    );
    await page.getByRole("button", { name: "Refresh deployments" }).click();
    await refreshRequestPromise;

    const configRequestPromise = page.waitForRequest(
      (request) => request.method() === "PATCH" && request.url().endsWith("/api/board/widgets/widget-deploy-monitor"),
    );
    await page.getByRole("button", { name: "Load next 5" }).click();
    const configRequest = await configRequestPromise;
    expect(configRequest.postDataJSON()).toEqual({
      config: { filter: "active", limit: 5, offset: 5 },
    });

    expect(card).toBeDefined();
    expect(badHttpResponses.all(), badHttpResponses.summary()).toEqual([]);
  });
});

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

const deployMonitorManifest = {
  id: "deploy_monitor",
  version: "0.1.0",
  name: "Deploy Monitor",
  category: "monitoring",
  description: "Generated deployment status widget rendered from a view blueprint.",
  min_size: "1x1",
  preferred_size: "2x2",
  allowed_sizes: ["1x1", "2x2", "4x2"],
  refresh_policy: { mode: "interval", interval_seconds: 60 },
  lifecycle_policy: { stateful: false, expires: false, default_ttl_seconds: null },
  runtime_policy: {
    start_timeout_seconds: 10,
    refresh_timeout_seconds: 10,
    heartbeat_timeout_seconds: 120,
    max_retries: 3,
    retry_backoff_seconds: 2,
    stale_after_seconds: 300,
  },
  permissions: ["network"],
  renderer: { kind: "blueprint", blueprint: "view.blueprint.json" },
};

const deployMonitorBlueprint = {
  blueprint_version: "1",
  widget_id: "deploy_monitor",
  layouts: {
    medium: {
      type: "stack",
      gap: "sm",
      children: [
        {
          type: "row",
          gap: "md",
          children: [
            {
              type: "stat",
              label: "Success rate",
              value_path: "output.score",
              emphasis: "primary",
              status_path: "output.health",
              status_map: { healthy: "ok", degraded: "warn", failed: "critical" },
            },
            { type: "stat", label: "Missing metric", value_path: "output.does_not_exist", emphasis: "secondary" },
          ],
        },
        { type: "progress", label: "Rollout", value_path: "output.progress", max_literal: 100 },
        {
          type: "text",
          literal: "Degraded mode",
          variant: "caption",
          show_if: { path: "output.degraded_reason", op: "exists" },
        },
        {
          type: "list",
          items_path: "items",
          limit: 2,
          item: {
            primary_path: "title",
            secondary_path: "env",
            meta_path: "duration",
            href_path: "url",
            status_path: "status",
            status_map: { ok: "ok", warn: "warn", failed: "critical" },
          },
        },
        {
          type: "row",
          gap: "sm",
          children: [
            { type: "action_button", label: "Refresh deployments", action: "refresh", style: "secondary" },
            {
              type: "action_button",
              label: "Load next 5",
              action: "config_patch",
              config_patch: { offset: 5 },
              style: "primary",
            },
          ],
        },
      ],
    },
  },
};

const mockRegistry = {
  deploy_monitor: {
    manifest: deployMonitorManifest,
    config_schema: { type: "object", properties: {} },
    blueprint: deployMonitorBlueprint,
    plugin: {
      widget_id: "deploy_monitor",
      version: "0.1.0",
      enabled: true,
      installed: true,
      is_core: false,
      source_type: "generated",
    },
  },
};

const mockBoard = {
  id: "blueprint-board",
  name: "Monitoring station",
  widgets: [
    {
      id: "widget-deploy-monitor",
      board_id: "blueprint-board",
      widget_id: "deploy_monitor",
      title: "Deploy Monitor",
      size: "2x2",
      position_index: 0,
      config: { filter: "active", limit: 5, offset: 0 },
      state: {
        output: { score: 87, health: "healthy", progress: 64 },
        items: [
          {
            title: "api rollout",
            env: "prod",
            duration: "4m12s",
            status: "ok",
            url: "https://example.com/deployments/api",
          },
          { title: "web rollout", env: "prod", duration: "2m03s", status: "warn", url: "" },
          { title: "worker rollout", env: "prod", duration: "7m44s", status: "failed", url: null },
        ],
      },
      lifecycle_state: "running",
      status_message: null,
      freshness_at: new Date().toISOString(),
      expires_at: null,
      last_error: null,
      last_heartbeat: new Date().toISOString(),
      service_started_at: new Date(Date.now() - 30 * 60_000).toISOString(),
      service_uptime_seconds: 1800,
      restart_count: 0,
      consecutive_failures: 0,
      blueprint: deployMonitorBlueprint,
    },
  ],
};
