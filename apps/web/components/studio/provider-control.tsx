"use client";

import type { AIModelOption, AIProvider } from "@/lib/types";
import { formatControlLabel, formatModelOptionLabel } from "@/components/studio/provider-utils";

const SELECT_CLASS =
  "rounded-control border border-edge bg-surface-inset px-3 py-2 text-sm text-slate-100 outline-none focus:border-accent/40";

/**
 * The single, compact provider / model / effort control for the whole studio.
 * Rendered exactly once (P4.1 removed the duplicated advanced copy).
 */
export function ProviderControl({
  providers,
  selectedProvider,
  modelOptions,
  selectedModel,
  reasoningEffortOptions,
  selectedReasoningEffort,
  onProviderChange,
  onModelChange,
  onReasoningEffortChange,
}: {
  providers: AIProvider[];
  selectedProvider: string;
  modelOptions: AIModelOption[];
  selectedModel: string;
  reasoningEffortOptions: string[];
  selectedReasoningEffort: string;
  onProviderChange: (providerId: string) => void;
  onModelChange: (modelId: string) => void;
  onReasoningEffortChange: (effort: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="grid min-w-[8rem] flex-1 gap-1.5">
        <span className="text-[11px] uppercase tracking-[0.16em] text-slate-500">Provider</span>
        <select
          aria-label="Provider"
          value={selectedProvider}
          onChange={(event) => onProviderChange(event.target.value)}
          className={SELECT_CLASS}
        >
          {providers.map((provider) => (
            <option key={provider.provider_id} value={provider.provider_id}>
              {provider.label}
            </option>
          ))}
        </select>
      </label>

      {modelOptions.length > 0 ? (
        <label className="grid min-w-[9rem] flex-1 gap-1.5">
          <span className="text-[11px] uppercase tracking-[0.16em] text-slate-500">Model</span>
          <select
            aria-label="Model"
            value={selectedModel}
            onChange={(event) => onModelChange(event.target.value)}
            className={SELECT_CLASS}
          >
            {modelOptions.map((model) => (
              <option key={model.id} value={model.id}>
                {formatModelOptionLabel(model)}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {reasoningEffortOptions.length > 0 ? (
        <label className="grid min-w-[7rem] flex-1 gap-1.5">
          <span className="text-[11px] uppercase tracking-[0.16em] text-slate-500">Intelligence</span>
          <select
            aria-label="Intelligence"
            value={selectedReasoningEffort}
            onChange={(event) => onReasoningEffortChange(event.target.value)}
            className={SELECT_CLASS}
          >
            {reasoningEffortOptions.map((effort) => (
              <option key={effort} value={effort}>
                {formatControlLabel(effort)}
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </div>
  );
}
