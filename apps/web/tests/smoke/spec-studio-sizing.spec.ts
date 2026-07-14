import { expect, test, type Page, type WebSocketRoute } from "@playwright/test";

import { collectBadHttpResponses } from "../helpers/http";

test("lets users select a strict widget size before easy generation", async ({ page }) => {
  const badHttpResponses = collectBadHttpResponses(page);
  let requestedIdea = "";
  await mockSpecStudioApi(page, (idea) => {
    requestedIdea = idea;
  });

  await page.goto("/studio");

  await expect(page.getByRole("heading", { name: "Spec Studio" })).toBeVisible();

  // The strict-size chip row lives directly beneath the idea input. Selecting a
  // size must not mutate any feedback box — it is passed through the request.
  const sizeButton = page.getByRole("group", { name: "Strict size" }).getByRole("button", { name: "2x4", exact: true });
  await expect(sizeButton).toHaveAttribute("aria-pressed", "false");

  await sizeButton.click();

  await expect(sizeButton).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("button", { name: "Generate", exact: true }).click();

  await expect.poll(() => requestedIdea).toContain("Use 2x4 as the preferred widget size.");
  expect(badHttpResponses.all(), badHttpResponses.summary()).toEqual([]);
});

test("streams generation updates over the board websocket", async ({ page }) => {
  const badHttpResponses = collectBadHttpResponses(page);
  let jobFetchCount = 0;
  let finalizeJob = false;
  let streamSocket: WebSocketRoute | null = null;

  await page.routeWebSocket(/\/api\/board\/stream/, (ws) => {
    streamSocket = ws;
  });
  await mockSpecStudioApi(page, () => undefined);
  // Authoritative per-job REST payload; each websocket-triggered refresh bumps
  // the step label so the test can attribute UI updates to individual fetches.
  await page.route("**/api/ai/easy-generation/jobs/job-spec-size", async (route) => {
    jobFetchCount += 1;
    const job = finalizeJob
      ? { ...mockGenerationJob, status: "review_required", current_step: null, progress: 100 }
      : { ...mockGenerationJob, status: "running", current_step: `streamed-step-${jobFetchCount}`, progress: 40 };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        job,
        test_box: finalizeJob ? mockStreamedTestBox : null,
        feedback_categories: ["name", "sizing", "ui", "feature"],
      }),
    });
  });

  await page.goto("/studio");
  await expect(page.getByRole("heading", { name: "Spec Studio" })).toBeVisible();

  await page.getByRole("button", { name: "Generate", exact: true }).click();

  // While generating, the hook connects to /board/stream and resyncs once via REST.
  await expect.poll(() => streamSocket !== null).toBe(true);
  await expect.poll(() => jobFetchCount).toBeGreaterThanOrEqual(1);
  // Let the connect/open transition settle; a healthy socket runs no polling timer.
  await page.waitForTimeout(1500);
  const settledCount = jobFetchCount;
  await expect(page.getByText(`streamed-step-${settledCount}`)).toBeVisible();

  // A generation event for another job must not trigger a refresh.
  streamSocket!.send(JSON.stringify(generationEvent("job-other")));
  await page.waitForTimeout(500);
  expect(jobFetchCount).toBe(settledCount);
  await expect(page.getByText(`streamed-step-${settledCount}`)).toBeVisible();

  // A matching event triggers exactly one authoritative REST fetch.
  streamSocket!.send(JSON.stringify(generationEvent("job-spec-size")));
  await expect.poll(() => jobFetchCount).toBe(settledCount + 1);
  await expect(page.getByText(`streamed-step-${settledCount + 1}`)).toBeVisible();

  // Easy generation keeps delivering the test-box payload from the REST response.
  finalizeJob = true;
  streamSocket!.send(JSON.stringify(generationEvent("job-spec-size")));
  await expect(page.getByText("Streamed Test Widget").first()).toBeVisible();

  expect(badHttpResponses.all(), badHttpResponses.summary()).toEqual([]);
});

test("enables approve then install following the backend job state machine", async ({ page }) => {
  const badHttpResponses = collectBadHttpResponses(page);
  await page.routeWebSocket(/\/api\/board\/stream/, () => {});
  await mockSpecStudioApi(page, () => undefined);

  // Backend contract: jobs finish at status "completed" (install_blocked=true);
  // approve moves them to "review_required" (install_blocked=false); install
  // accepts "review_required"/"approved".
  let jobState = {
    ...mockGenerationJob,
    status: "completed",
    current_step: "completed",
    progress: 100,
    install_blocked: true,
    completed_at: new Date().toISOString(),
    generation_mode: "cli",
  };
  await page.route("**/api/ai/easy-generation/jobs/job-spec-size", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ job: jobState, test_box: mockStreamedTestBox, feedback_categories: ["name", "sizing", "ui", "feature"] }),
    }),
  );
  await page.route("**/api/ai/generation/jobs/job-spec-size/approve", (route) => {
    jobState = { ...jobState, status: "review_required", install_blocked: false };
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(jobState) });
  });
  await page.route("**/api/ai/generation/jobs/job-spec-size/install", (route) => {
    jobState = { ...jobState, status: "installed" };
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(jobState) });
  });

  await page.goto("/studio");
  await expect(page.getByRole("heading", { name: "Spec Studio" })).toBeVisible();
  await page.getByRole("button", { name: "Generate", exact: true }).click();

  const approve = page.getByRole("button", { name: "Approve", exact: true });
  const install = page.getByRole("button", { name: "Install", exact: true });

  // A freshly completed job is approvable but not yet installable.
  await expect(approve).toBeEnabled();
  await expect(install).toBeDisabled();
  await expect(page.getByText(/Approve the job first/)).toBeVisible();

  // CLI-mode jobs get a plain informational line, never the offline template warning.
  await expect(page.getByText("Generated through the local Codex CLI")).toBeVisible();
  await expect(page.getByText(/Generated in offline template mode/)).toHaveCount(0);

  await approve.click();

  // Approved: install opens up, approve reports it is already done.
  await expect(install).toBeEnabled();
  await expect(approve).toBeDisabled();
  await expect(page.getByText(/Already approved/)).toBeVisible();

  await install.click();
  await expect(install).toBeDisabled();

  expect(badHttpResponses.all(), badHttpResponses.summary()).toEqual([]);
});

function generationEvent(jobId: string) {
  return {
    type: "generation.job.updated",
    category: "generation",
    payload: { job_id: jobId, stage: "codegen", progress: 40 },
  };
}

async function mockSpecStudioApi(page: Page, onEasyGeneration: (idea: string) => void) {
  await page.route("**/api/ai/providers", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          provider_id: "codex",
          label: "Codex",
          status: "ready",
          default_model_id: "local-test",
          supported_model_ids: ["local-test"],
          supports_idea_to_spec: true,
          supports_codegen: true,
          supports_review: true,
        },
      ]),
    }),
  );
  await page.route("**/api/ai/generation/jobs", async (route) => {
    if (route.request().method() === "POST") {
      const payload = (await route.request().postDataJSON()) as { idea?: string };
      onEasyGeneration(payload.idea ?? "");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockGenerationJob),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });
  // Per-job authoritative fetches issued by the generation transport hook.
  await page.route("**/api/ai/generation/jobs/*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockGenerationJob),
    }),
  );
  await page.route("**/api/ai/easy-generation/jobs/*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ job: mockGenerationJob, test_box: null, feedback_categories: ["name", "sizing", "ui", "feature"] }),
    }),
  );
  await page.route("**/api/ai/easy-generation/jobs", async (route) => {
    const payload = (await route.request().postDataJSON()) as { idea?: string };
    onEasyGeneration(payload.idea ?? "");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ job: mockGenerationJob, test_box: null, feedback_categories: ["name", "sizing", "ui", "feature"] }),
    });
  });
  await page.route("**/api/specs/preview", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockSpecPreview),
    }),
  );
  await page.route("**/api/ai/generation/preview**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ steps: [] }),
    }),
  );
}

const mockGenerationJob = {
  id: "job-spec-size",
  widget_id: "ops_status",
  provider_id: "codex",
  model_id: "local-test",
  selected_version: "0.1.0",
  artifact_version: 1,
  status: "queued",
  idea: "Build a compact operations status widget.",
  install_blocked: false,
  error_message: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  completed_at: null,
  artifacts: [],
  logs: [],
  install_target: null,
  diff_preview: [],
};

const mockStreamedTestBox = {
  job_id: "job-spec-size",
  widget_id: "ops_status",
  stage_id: null,
  name: "Streamed Test Widget",
  description: "Delivered through the websocket-triggered REST refresh.",
  category: "custom",
  size: "2x2",
  allowed_sizes: ["2x2"],
  manifest: { id: "ops_status", name: "Streamed Test Widget", preferred_size: "2x2" },
  config_schema: {},
  renderer: {},
  service: {},
  initial_config: {},
  initial_state: {},
  files: [],
  install_blocked: false,
  review_required: true,
};

const mockSpecPreview = {
  valid: true,
  errors: [],
  stage_id: "stage-spec-size",
  normalized_spec: {
    id: "custom_widget",
    name: "Custom Widget",
    category: "custom",
    description: "Describe the behavior of the widget here.",
    min_size: "2x2",
    preferred_size: "4x2",
    refresh_policy: { mode: "interval", interval_seconds: 300 },
    source_type: "api",
    permissions: ["network"],
    output_schema: { primary: "headline", secondary: "status" },
    renderer_type: "card",
    lifecycle_policy: { expires: false, stateful: true },
  },
  manifest_preview: {
    id: "custom_widget",
    version: "0.1.0",
    name: "Custom Widget",
    category: "custom",
    description: "Describe the behavior of the widget here.",
    min_size: "2x2",
    preferred_size: "4x2",
    allowed_sizes: ["2x2", "4x2"],
    refresh_policy: { mode: "interval", interval_seconds: 300 },
    lifecycle_policy: { expires: false, stateful: true },
    runtime_policy: {},
    permissions: ["network"],
    renderer: { target: "react", module: "@widgets/custom_widget/renderer", export_name: "CustomWidgetRenderer" },
  },
  scaffold_preview: { files: [] },
};
