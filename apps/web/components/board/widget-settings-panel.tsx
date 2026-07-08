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
  format?: string;
  enum?: string[];
  default?: JsonValue;
  minimum?: number;
  maximum?: number;
  minItems?: number;
  maxItems?: number;
  "x-ui-hidden"?: boolean;
  items?: {
    type?: string;
    enum?: string[];
    required?: string[];
    properties?: Record<string, SchemaProperty>;
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

function isHiddenProperty(property: SchemaProperty) {
  return property["x-ui-hidden"] === true;
}

function toDatetimeLocalValue(value: JsonValue | undefined) {
  if (typeof value !== "string" || !value.trim()) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function fromDatetimeLocalValue(value: string) {
  if (!value.trim()) {
    return "";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toISOString();
}

function objectArrayValue(value: JsonValue | undefined) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is JsonObject => typeof item === "object" && item !== null && !Array.isArray(item));
}

function defaultValueForProperty(property: SchemaProperty): JsonValue {
  if (property.default !== undefined) {
    return property.default;
  }
  if (property.type === "string" && property.format === "date-time") {
    return new Date(Date.now() + 60 * 60 * 1000).toISOString();
  }
  if (property.type === "integer" || property.type === "number") {
    return property.minimum ?? 0;
  }
  if (property.type === "boolean") {
    return false;
  }
  if (property.type === "array") {
    return [];
  }
  return "";
}

function defaultObjectItem(properties: Record<string, SchemaProperty> | undefined) {
  const item: JsonObject = {};
  for (const [key, property] of Object.entries(properties ?? {})) {
    item[key] =
      key === "id"
        ? `item-${Date.now().toString(36)}`
        : key === "label"
          ? "Timer"
          : defaultValueForProperty(property);
  }
  return item;
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
  const visibleProperties = Object.fromEntries(
    Object.entries(properties).filter(([, property]) => !isHiddenProperty(property)),
  );

  async function handleSave() {
    setSaving(true);
    try {
      await onSave(draft);
    } finally {
      setSaving(false);
    }
  }

  return (
    <details className="mt-4 overflow-hidden rounded-panel border border-edge bg-surface-raised">
      <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-slate-100 transition hover:bg-white/[0.04]">
        <span className="flex items-center justify-between gap-3">
          <span>Source settings</span>
          <span className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
            {Object.keys(visibleProperties).length} fields
          </span>
        </span>
      </summary>
      <div className="space-y-4 border-t border-edge px-4 py-4">
        {providerStates.length > 0 ? (
          <div className="grid gap-2">
            {providerStates.map((provider) => (
              <div
                key={`${provider.provider_id}-${provider.label}`}
                className="rounded-panel border border-edge bg-surface-inset px-3 py-2.5 text-xs text-slate-300"
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

        {Object.entries(visibleProperties).map(([key, property]) => {
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
            const objectValues = objectArrayValue(currentValue);
            const itemProperties = property.items?.properties;
            if (property.items?.type === "object" && itemProperties) {
              const maxItems = property.maxItems ?? 8;
              return (
                <div key={key} className="space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm text-slate-200">{label}</p>
                    <span className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                      {objectValues.length}/{maxItems}
                    </span>
                  </div>
                  <div className="space-y-2">
                    {objectValues.map((item, index) => (
                      <div key={`${key}-${index}`} className="rounded-panel border border-edge bg-surface-inset p-2">
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <span className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                            {label} {index + 1}
                          </span>
                          <button
                            type="button"
                            onClick={() =>
                              setDraft((current) => ({
                                ...current,
                                [key]: objectValues.filter((_, itemIndex) => itemIndex !== index),
                              }))
                            }
                            className="flex h-6 w-6 items-center justify-center rounded-control border border-edge bg-surface-raised text-xs text-slate-300 transition hover:border-rose-300/25 hover:bg-rose-300/12 hover:text-rose-100"
                          >
                            x
                          </button>
                        </div>
                        <div className="grid gap-2">
                          {Object.entries(itemProperties).map(([itemKey, itemProperty]) => {
                            if (itemKey === "id") {
                              return null;
                            }
                            const itemValue = item[itemKey];
                            const itemLabel = fieldLabel(itemKey, itemProperty);
                            const updateItem = (nextValue: JsonValue) =>
                              setDraft((current) => ({
                                ...current,
                                [key]: objectValues.map((candidate, itemIndex) =>
                                  itemIndex === index ? { ...candidate, [itemKey]: nextValue } : candidate,
                                ),
                              }));

                            return (
                              <label key={itemKey} className="grid gap-1.5">
                                <span className="text-xs text-slate-300">{itemLabel}</span>
                                <input
                                  type={itemProperty.type === "integer" || itemProperty.type === "number" ? "number" : itemProperty.format === "date-time" ? "datetime-local" : "text"}
                                  min={itemProperty.minimum}
                                  max={itemProperty.maximum}
                                  value={
                                    itemProperty.format === "date-time"
                                      ? toDatetimeLocalValue(itemValue)
                                      : typeof itemValue === "number" || typeof itemValue === "string"
                                        ? String(itemValue)
                                        : String(defaultValueForProperty(itemProperty))
                                  }
                                  onChange={(event) => {
                                    if (itemProperty.format === "date-time") {
                                      updateItem(fromDatetimeLocalValue(event.target.value));
                                      return;
                                    }
                                    if (itemProperty.type === "integer" || itemProperty.type === "number") {
                                      updateItem(Number(event.target.value));
                                      return;
                                    }
                                    updateItem(event.target.value);
                                  }}
                                  className="rounded-control border border-edge bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300/35"
                                />
                              </label>
                            );
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                  <button
                    type="button"
                    disabled={objectValues.length >= maxItems}
                    onClick={() =>
                      setDraft((current) => ({
                        ...current,
                        [key]: [...objectValues, defaultObjectItem(itemProperties)],
                      }))
                    }
                    className="rounded-control border border-cyan-300/20 bg-cyan-300/10 px-3 py-2 text-xs text-cyan-100 transition hover:bg-cyan-300/18 disabled:opacity-45"
                  >
                    Add {label.toLowerCase()}
                  </button>
                </div>
              );
            }
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
                          className={`rounded-control border px-3 py-1.5 text-xs transition ${
                            selected
                              ? "border-cyan-300/30 bg-cyan-300/15 text-cyan-50"
                              : "border-edge bg-surface-raised text-slate-300 hover:-translate-y-0.5 hover:bg-white/10"
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
                  className="rounded-control border border-edge bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300/35"
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
                  className="rounded-control border border-edge bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300/35"
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
                  className="rounded-control border border-edge bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300/35"
                />
              </label>
            );
          }

          if (property.type === "string" && property.format === "date-time") {
            return (
              <label key={key} className="grid gap-2">
                <span className="text-sm text-slate-200">{label}</span>
                <input
                  type="datetime-local"
                  value={toDatetimeLocalValue(currentValue)}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      [key]: fromDatetimeLocalValue(event.target.value),
                    }))
                  }
                  className="rounded-control border border-edge bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300/35"
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
                className="rounded-control border border-edge bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300/35"
              />
            </label>
          );
        })}

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving}
            className="rounded-control border border-cyan-300/20 bg-cyan-300/10 px-4 py-2 text-xs text-cyan-100 transition duration-200 hover:-translate-y-0.5 hover:bg-cyan-300/20 disabled:opacity-60"
          >
            {saving ? "Saving..." : "Apply settings"}
          </button>
          <button
            type="button"
            onClick={() => setDraft(value)}
            className="rounded-control border border-edge px-4 py-2 text-xs text-slate-300 transition duration-200 hover:-translate-y-0.5 hover:bg-white/10"
          >
            Reset
          </button>
        </div>
      </div>
    </details>
  );
}
