import { parseBlueprint, type Blueprint } from "@/lib/blueprint";
import type {
  GenerationArtifact,
  GenerationJob,
  GenerationTestBox,
  JsonObject,
  TileSize,
} from "@/lib/types";

export const allowedWidgetSizes = ["1x1", "1x2", "2x2", "4x2", "2x4", "4x4"] as const satisfies TileSize[];
export const defaultWidgetSize: TileSize = "4x2";

/** Sizes offered by the live-preview tier switcher (task-specified subset). */
export const previewSizes = ["1x1", "2x2", "4x2", "2x4", "4x4"] as const satisfies TileSize[];

/** Pixel footprint per size for the sized preview frame (approximate board tile). */
export const previewFrameDimensions: Record<TileSize, { width: number; height: number }> = {
  "1x1": { width: 150, height: 130 },
  "1x2": { width: 150, height: 264 },
  "2x2": { width: 300, height: 264 },
  "4x2": { width: 560, height: 264 },
  "2x4": { width: 300, height: 520 },
  "4x4": { width: 560, height: 520 },
};

export interface WidgetBrief {
  name: string;
  description: string;
  category: string;
  preferredSize: string | null;
  sizeAllowed: boolean;
}

export type WidgetSizeState = "valid" | "invalid" | "unset";

export function isJsonObject(value: unknown): value is JsonObject {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function pickString(...values: unknown[]): string | null {
  const found = values.find((value) => typeof value === "string" && value.trim().length > 0);
  return typeof found === "string" ? found : null;
}

export function isAllowedWidgetSize(value: string | null): value is TileSize {
  return Boolean(value) && allowedWidgetSizes.includes(value as TileSize);
}

export function getWidgetSizeState(value: string | null): WidgetSizeState {
  if (!value) {
    return "unset";
  }
  return isAllowedWidgetSize(value) ? "valid" : "invalid";
}

const CODE_LANGUAGE_HINTS: Record<string, string> = {
  py: "python",
  json: "json",
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  md: "markdown",
};

export function guessLanguage(path: string): string {
  const extension = path.split(".").pop()?.toLowerCase() ?? "";
  return CODE_LANGUAGE_HINTS[extension] ?? "text";
}

function parseJsonFile(content: string): JsonObject | null {
  try {
    const parsed = JSON.parse(content) as unknown;
    return isJsonObject(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function findArtifactPayload(job: GenerationJob | null, artifactNames: string[]): JsonObject | null {
  if (!job) {
    return null;
  }
  for (const artifact of job.artifacts) {
    const nameMatches = artifactNames.some(
      (name) => artifact.artifact_type.includes(name) || artifact.stage.includes(name),
    );
    if (nameMatches && artifact.payload) {
      return artifact.payload;
    }
    const matchingFile = artifact.files.find((file) =>
      artifactNames.some((name) => file.path.toLowerCase().includes(name.toLowerCase()) && file.path.endsWith(".json")),
    );
    if (matchingFile) {
      const parsed = parseJsonFile(matchingFile.content);
      if (parsed) {
        return parsed;
      }
    }
  }
  return null;
}

export function selectCodeArtifact(job: GenerationJob | null): GenerationArtifact | null {
  return job?.artifacts.find((artifact) => artifact.stage === "codegen" && artifact.artifact_type === "package") ?? null;
}

export function selectManifest(job: GenerationJob | null, testBox: GenerationTestBox | null): JsonObject | null {
  return testBox?.manifest ?? findArtifactPayload(job, ["manifest", "manifest_preview"]);
}

export function selectSpec(job: GenerationJob | null): JsonObject | null {
  return findArtifactPayload(job, ["spec", "normalized_spec", "spec_draft"]);
}

/**
 * Locate the widget view blueprint for the live preview. The document ships as a
 * `view.blueprint.json` file in the test-box / codegen package; it may also ride
 * along on the manifest or codegen payload. Returns a parsed blueprint or null.
 */
export function extractBlueprint(
  job: GenerationJob | null,
  testBox: GenerationTestBox | null,
  manifest: JsonObject | null,
): Blueprint | null {
  const fileSources = [
    testBox?.files,
    selectCodeArtifact(job)?.files,
    ...(job?.artifacts.map((artifact) => artifact.files) ?? []),
  ];
  for (const files of fileSources) {
    const blueprintFile = files?.find((file) => file.path.toLowerCase().endsWith("view.blueprint.json"));
    if (blueprintFile) {
      const parsed = parseBlueprint(parseJsonFile(blueprintFile.content));
      if (parsed) {
        return parsed;
      }
    }
  }

  const inlineSources: unknown[] = [
    manifest?.blueprint,
    (testBox?.renderer as JsonObject | undefined)?.blueprint,
    selectCodeArtifact(job)?.payload?.package && isJsonObject(selectCodeArtifact(job)?.payload?.package)
      ? (selectCodeArtifact(job)?.payload?.package as JsonObject).blueprint
      : undefined,
    findArtifactPayload(job, ["blueprint"]),
  ];
  for (const source of inlineSources) {
    const parsed = parseBlueprint(source ?? null);
    if (parsed) {
      return parsed;
    }
  }

  return null;
}

export function buildSampleState(
  job: GenerationJob | null,
  testBox: GenerationTestBox | null,
  manifest: JsonObject | null,
  spec: JsonObject | null,
): JsonObject {
  if (testBox?.initial_state && Object.keys(testBox.initial_state).length > 0) {
    return testBox.initial_state;
  }
  const artifactState = findArtifactPayload(job, ["sample_state", "sample-state", "state"]);
  if (artifactState) {
    return artifactState;
  }
  const payloadState = [manifest?.sample_state, spec?.sample_state, spec?.state].find(isJsonObject);
  if (payloadState) {
    return payloadState;
  }
  return {
    title: typeof manifest?.name === "string" ? manifest.name : job?.widget_id ?? "Generated widget",
    status: job?.status ?? "draft",
    freshness: "sample",
    summary: typeof manifest?.description === "string" ? manifest.description : "Generated sample state",
  };
}

export function buildWidgetBrief(
  job: GenerationJob | null,
  testBox: GenerationTestBox | null,
  manifest: JsonObject | null,
  spec: JsonObject | null,
): WidgetBrief {
  const preferredSize = pickString(testBox?.size, manifest?.preferred_size, spec?.preferred_size, spec?.size);
  return {
    name: pickString(testBox?.name, manifest?.name, spec?.name, job?.widget_id) ?? "Generated widget",
    description:
      pickString(testBox?.description, manifest?.description, spec?.description, job?.idea) ?? "Generated widget draft",
    category: pickString(testBox?.category, manifest?.category, spec?.category) ?? "custom",
    preferredSize,
    sizeAllowed: isAllowedWidgetSize(preferredSize),
  };
}

/** Encode the chosen strict size into the idea string (no feedback-box side effects). */
export function buildIdeaWithSelectedSize(trimmedIdea: string, size: TileSize): string {
  const sizeInstruction = `Use ${size} as the preferred widget size.`;
  return trimmedIdea ? `${trimmedIdea} ${sizeInstruction}` : sizeInstruction;
}

export function replaceJob(items: GenerationJob[], nextJob: GenerationJob): GenerationJob[] {
  const remaining = items.filter((item) => item.id !== nextJob.id);
  return [nextJob, ...remaining];
}

export function formatStateValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "null";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

export const GENERATING_STATUSES = new Set<GenerationJob["status"]>(["queued", "running"]);

export function isGenerating(job: GenerationJob | null): boolean {
  return Boolean(job && GENERATING_STATUSES.has(job.status));
}
