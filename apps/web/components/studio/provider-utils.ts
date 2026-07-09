import type { AIModelOption, AIProvider } from "@/lib/types";

/** Resolve the selectable model options for a provider, with a defensive fallback. */
export function getProviderModelOptions(provider: AIProvider): AIModelOption[] {
  if (provider.model_options?.length) {
    return provider.model_options;
  }
  return provider.supported_model_ids.map((id) => ({
    id,
    label: id,
    intelligence_level: null,
    speed_level: null,
    reasoning_effort_options: [],
    source: "fallback",
  }));
}

export function getDefaultModelId(provider: AIProvider): string {
  const options = getProviderModelOptions(provider);
  if (provider.default_model_id && options.some((option) => option.id === provider.default_model_id)) {
    return provider.default_model_id;
  }
  return options[0]?.id ?? "";
}

export function getDefaultReasoningEffort(provider: AIProvider, modelId: string): string {
  const model = getProviderModelOptions(provider).find((option) => option.id === modelId);
  const options = model?.reasoning_effort_options ?? [];
  if (options.includes("medium")) {
    return "medium";
  }
  return options[0] ?? "";
}

export function formatModelOptionLabel(model: AIModelOption): string {
  const details = [model.intelligence_level, model.speed_level]
    .filter((value): value is string => Boolean(value))
    .map(formatControlLabel);
  const label = model.label || model.id;
  return details.length ? `${label} (${details.join(" / ")})` : label;
}

export function formatControlLabel(value: string): string {
  return value
    .split(/[-_ ]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
