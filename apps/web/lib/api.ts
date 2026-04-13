import { API_BASE_URL } from "@/lib/constants";
import type {
  AIProvider,
  BoardState,
  GenerationPipelinePreview,
  JsonObject,
  SpecValidationResult,
  TileSize,
  WidgetPlugin,
  WidgetPreset,
  WidgetRegistryEntry,
} from "@/lib/types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed for ${path}`);
  }

  return response.json() as Promise<T>;
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
