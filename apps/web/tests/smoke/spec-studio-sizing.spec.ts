import { expect, test, type Page } from "@playwright/test";

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
