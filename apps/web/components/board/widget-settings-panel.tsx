"use client";

import { useEffect, useState } from "react";

import type { JsonObject, JsonValue } from "@/lib/types";

interface WidgetSettingsPanelProps {
  configSchema: JsonObject;
  value: JsonObject;
  onSave: (config: JsonObject) => void | Promise<void>;
  providerStates?: Array<{
    provider_id?: string;
    label?: string;
    status?: string;
    error?: string | null;
  }>;
}

interface SchemaProperty {
  type?: string;
  title?: string;
  enum?: string[];
  default?: JsonValue;
  minimum?: number;
  maximum?: number;
  items?: {
    type?: string;
    enum?: string[];
  };
}

function fieldLabel(key: string, property: SchemaProperty) {
  if (typeof property.title === "string" && property.title.trim()) {
    return property.title;
  }
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function stringArrayValue(value: JsonValue | undefined) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
}

export function WidgetSettingsPanel({
  configSchema,
  value,
  onSave,
  providerStates = [],
}: WidgetSettingsPanelProps) {
  const [draft, setDraft] = useState<JsonObject>(value);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  const properties = (configSchema.properties as Record<string, SchemaProperty> | undefined) ?? {};

  async function handleSave() {
    setSaving(true);
    try {
      await onSave(draft);
    } finally {
      setSaving(false);
    }
  }

  return (
    <details className="mt-4 overflow-hidden rounded-[24px] border border-white/10 bg-white/[0.03]">
      <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-slate-100 transition hover:bg-white/[0.04]">
        <span className="flex items-center justify-between gap-3">
          <span>Source settings</span>
          <span className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
            {Object.keys(properties).length} fields
          </span>
        </span>
      </summary>
      <div className="space-y-4 border-t border-white/10 px-4 py-4">
        {providerStates.length > 0 ? (
          <div className="grid gap-2">
            {providerStates.map((provider) => (
              <div
                key={`${provider.provider_id}-${provider.label}`}
                className="rounded-[20px] border border-white/10 bg-black/20 px-3 py-2.5 text-xs text-slate-300"
              >
                <div className="flex items-center justify-between gap-3">
                  <span>{provider.label ?? provider.provider_id ?? "provider"}</span>
                  <span className="uppercase tracking-[0.18em] text-slate-500">
                    {provider.status ?? "unknown"}
                  </span>
                </div>
                {provider.error ? <p className="mt-1 text-rose-300">{provider.error}</p> : null}
              </div>
            ))}
          </div>
        ) : null}

        {Object.entries(properties).map(([key, property]) => {
          const currentValue = draft[key];
          const label = fieldLabel(key, property);
          if (property.type === "boolean") {
            return (
              <label key={key} className="flex items-center justify-between gap-3 text-sm text-slate-200">
                <span>{label}</span>
                <input
                  type="checkbox"
                  checked={Boolean(currentValue)}
                  onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.checked }))}
                  className="h-4 w-4 rounded border-white/20 bg-slate-950"
                />
              </label>
            );
          }

          if (property.type === "array") {
            const values = stringArrayValue(currentValue);
            if (Array.isArray(property.items?.enum)) {
              return (
                <div key={key} className="space-y-2">
                  <p className="text-sm text-slate-200">{label}</p>
                  <div className="flex flex-wrap gap-2">
                    {property.items.enum.map((option) => {
                      const selected = values.includes(option);
                      return (
                        <button
                          key={option}
                          type="button"
                          onClick={() =>
                            setDraft((current) => ({
                              ...current,
                              [key]: selected
                                ? values.filter((item) => item !== option)
                                : [...values, option],
                            }))
                          }
                          className={`rounded-full border px-3 py-1.5 text-xs transition ${
                            selected
                              ? "border-cyan-300/30 bg-cyan-300/15 text-cyan-50"
                              : "border-white/10 bg-white/5 text-slate-300 hover:-translate-y-0.5 hover:bg-white/10"
                          }`}
                        >
                          {option}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            }

            return (
              <label key={key} className="grid gap-2">
                <span className="text-sm text-slate-200">{label}</span>
                <textarea
                  value={values.join("\n")}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      [key]: event.target.value
                        .split("\n")
                        .map((item) => item.trim())
                        .filter(Boolean),
                    }))
                  }
                  rows={4}
                  className="rounded-[20px] border border-white/10 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300/35"
                />
              </label>
            );
          }

          if (Array.isArray(property.enum)) {
            return (
              <label key={key} className="grid gap-2">
                <span className="text-sm text-slate-200">{label}</span>
                <select
                  value={typeof currentValue === "string" ? currentValue : String(property.default ?? property.enum[0])}
                  onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.value }))}
                  className="rounded-[20px] border border-white/10 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300/35"
                >
                  {property.enum.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
            );
          }

          if (property.type === "integer" || property.type === "number") {
            return (
              <label key={key} className="grid gap-2">
                <span className="text-sm text-slate-200">{label}</span>
                <input
                  type="number"
                  min={property.minimum}
                  max={property.maximum}
                  value={typeof currentValue === "number" ? currentValue : Number(property.default ?? 0)}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      [key]: Number(event.target.value),
                    }))
                  }
                  className="rounded-[20px] border border-white/10 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300/35"
                />
              </label>
            );
          }

          return (
            <label key={key} className="grid gap-2">
              <span className="text-sm text-slate-200">{label}</span>
              <input
                type="text"
                value={typeof currentValue === "string" ? currentValue : String(property.default ?? "")}
                onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.value }))}
                className="rounded-[20px] border border-white/10 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300/35"
              />
            </label>
          );
        })}

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving}
            className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-4 py-2 text-xs text-cyan-100 transition duration-200 hover:-translate-y-0.5 hover:bg-cyan-300/20 disabled:opacity-60"
          >
            {saving ? "Saving..." : "Apply settings"}
          </button>
          <button
            type="button"
            onClick={() => setDraft(value)}
            className="rounded-full border border-white/10 px-4 py-2 text-xs text-slate-300 transition duration-200 hover:-translate-y-0.5 hover:bg-white/10"
          >
            Reset
          </button>
        </div>
      </div>
    </details>
  );
}
