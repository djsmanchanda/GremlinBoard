import { apiUrl } from "@/lib/constants";
import type {
  AIProvider,
  ApiCredential,
  AuthContext,
  BoardState,
  EasyGenerationJob,
  GenerationFeedbackRequest,
  GenerationFeedbackResponse,
  GenerationJob,
  GenerationPipelinePreview,
  JsonObject,
  ObservabilityOverview,
  SpecValidationResult,
  SystemSettings,
  TileSize,
  WidgetPlugin,
  WidgetPreset,
  WidgetRegistryEntry,
} from "@/lib/types";

const REQUEST_TIMEOUT_MS = 15000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const headers = new Headers(init?.headers);
  if (init?.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  try {
    const response = await fetch(apiUrl(path), {
      ...init,
      headers,
      cache: "no-store",
      signal: init?.signal ?? controller.signal,
    });

    if (!response.ok) {
      const body = await response.text();
      try {
        const parsed = JSON.parse(body) as { detail?: string };
        throw new Error(parsed.detail || `Request failed for ${path}`);
      } catch {
        throw new Error(body || `Request failed for ${path}`);
      }
    }

    return response.json() as Promise<T>;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error(`Request timed out for ${path}`);
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

export function fetchBoard() {
  return request<BoardState>("/board");
}

export function fetchRegistry() {
  return request<Record<string, WidgetRegistryEntry>>("/registry/widgets");
}

export function addWidget(preset: WidgetPreset) {
  return request("/board/widgets", {
    method: "POST",
    body: JSON.stringify({
      widget_id: preset.widget_id,
      title: preset.title,
      size: preset.size,
      config: preset.config,
    }),
  });
}

export function resizeWidget(widgetId: string, size: TileSize) {
  return request(`/board/widgets/${widgetId}/size`, {
    method: "PATCH",
    body: JSON.stringify({ size }),
  });
}

export function reorderWidgets(ordered_ids: string[]) {
  return request<BoardState>("/board/widgets/reorder", {
    method: "PATCH",
    body: JSON.stringify({ ordered_ids }),
  });
}

export function refreshWidget(widgetId: string) {
  return request<BoardState>(`/board/widgets/${widgetId}/refresh`, {
    method: "POST",
  });
}

export function stopWidget(widgetId: string) {
  return request<BoardState>(`/board/widgets/${widgetId}/stop`, {
    method: "POST",
  });
}

export function startWidget(widgetId: string) {
  return request<BoardState>(`/board/widgets/${widgetId}/start`, {
    method: "POST",
  });
}

export function removeWidget(widgetId: string) {
  return request<BoardState>(`/board/widgets/${widgetId}`, {
    method: "DELETE",
  });
}

export function updateWidget(widgetId: string, payload: { title?: string; config?: JsonObject }) {
  return request(`/board/widgets/${widgetId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function validateSpec(payload: Record<string, unknown>) {
  return request("/specs/validate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function previewSpecDocument(payload: { format: "json" | "yaml"; content: string }) {
  return request<SpecValidationResult>("/specs/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchPlugins() {
  return request<WidgetPlugin[]>("/plugins");
}

export function fetchAIProviders() {
  return request<AIProvider[]>("/ai/providers");
}

export function fetchGenerationPreview(params: { stageId: string; providerId: string }) {
  const query = new URLSearchParams({
    stage_id: params.stageId,
    provider_id: params.providerId,
  });
  return request<GenerationPipelinePreview>(`/ai/generation/preview?${query.toString()}`);
}

export function fetchGenerationJobs(widgetId?: string) {
  const query = widgetId ? `?widget_id=${encodeURIComponent(widgetId)}` : "";
  return request<GenerationJob[]>(`/ai/generation/jobs${query}`);
}

export function fetchGenerationJob(jobId: string) {
  return request<GenerationJob>(`/ai/generation/jobs/${jobId}`);
}

export function createGenerationJob(payload: {
  provider_id?: string;
  model_id?: string;
  fallback_provider_ids?: string[];
  stage_id?: string;
  idea?: string;
  regenerate_from_job_id?: string;
  version?: string;
}) {
  return request<GenerationJob>("/ai/generation/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createEasyGenerationJob(payload: {
  idea: string;
  provider_id?: string;
  model_id?: string;
  fallback_provider_ids?: string[];
  version?: string;
}) {
  return request<EasyGenerationJob>("/ai/easy-generation/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchEasyGenerationJob(jobId: string) {
  return request<EasyGenerationJob>(`/ai/easy-generation/jobs/${jobId}`);
}

export function submitGenerationFeedback(jobId: string, payload: GenerationFeedbackRequest) {
  return request<GenerationFeedbackResponse>(`/ai/generation/jobs/${jobId}/feedback`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function approveGenerationJob(jobId: string) {
  return request<GenerationJob>(`/ai/generation/jobs/${jobId}/approve`, {
    method: "POST",
  });
}

export function rejectGenerationJob(jobId: string, reason: string) {
  return request<GenerationJob>(`/ai/generation/jobs/${jobId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function installGenerationJob(jobId: string, enabled = true) {
  return request<GenerationJob>(`/ai/generation/jobs/${jobId}/install`, {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });
}

export function rollbackGeneratedWidget(widgetId: string, version: string) {
  return request<WidgetPlugin>(`/ai/generation/widgets/${widgetId}/rollback`, {
    method: "POST",
    body: JSON.stringify({ version }),
  });
}

export function fetchSystemContext() {
  return request<AuthContext>("/system/context");
}

export function fetchSystemSettings() {
  return request<SystemSettings>("/system/settings");
}

export function updateSystemSettings(payload: Partial<SystemSettings>) {
  return request<SystemSettings>("/system/settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function fetchApiCredentials() {
  return request<ApiCredential[]>("/system/credentials");
}

export function upsertApiCredential(payload: { id?: string; provider: string; label: string; value: string }) {
  return request<ApiCredential>(payload.id ? `/system/credentials/${payload.id}` : "/system/credentials", {
    method: "PUT",
    body: JSON.stringify({
      provider: payload.provider,
      label: payload.label,
      value: payload.value,
    }),
  });
}

export function deleteApiCredential(credentialId: string) {
  return request<{ status: string }>(`/system/credentials/${credentialId}`, {
    method: "DELETE",
  });
}

export function fetchObservabilityOverview(limit = 80) {
  return request<ObservabilityOverview>(`/observability/overview?limit=${limit}`);
}
