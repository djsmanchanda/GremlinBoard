"use client";

import { type KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from "react";

import { WIDGET_PRESETS } from "@/lib/widget-presets";
import { cn } from "@/lib/utils";
import type { WidgetPreset, WidgetRegistryEntry } from "@/lib/types";

interface CommandPaletteProps {
  open: boolean;
  registry: Record<string, WidgetRegistryEntry>;
  onClose: () => void;
  onSelect: (preset: WidgetPreset) => void;
}

interface CatalogItem extends WidgetPreset {
  category: string;
  description: string;
  providerDetail: string;
  refreshDetail: string;
  allowedSizes: string;
  sourceDetail: string;
}

function isAddableRegistryEntry(entry: WidgetRegistryEntry) {
  return entry.plugin == null || (entry.plugin.installed && entry.plugin.enabled);
}

function readStringConfig(preset: WidgetPreset, key: string) {
  const value = preset.config[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function readStringListConfig(preset: WidgetPreset, key: string) {
  const value = preset.config[key];
  if (!Array.isArray(value)) {
    return null;
  }
  const items = value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
  return items.length > 0 ? items.join(", ") : null;
}

function formatProviderDetail(preset: WidgetPreset, entry?: WidgetRegistryEntry) {
  return (
    readStringConfig(preset, "provider") ??
    readStringListConfig(preset, "sources") ??
    entry?.plugin?.source_type ??
    "local"
  );
}

function formatRefreshDetail(entry?: WidgetRegistryEntry) {
  if (!entry) {
    return "registry";
  }
  const { mode, interval_seconds: intervalSeconds } = entry.manifest.refresh_policy;
  return mode === "interval" ? `${mode} ${intervalSeconds}s` : mode;
}

function enrichPreset(preset: WidgetPreset, entry?: WidgetRegistryEntry): CatalogItem {
  const category = entry?.manifest.category ?? "custom";
  const description = entry?.manifest.description ?? preset.title;
  const sourceDetail = readStringConfig(preset, "sport") ?? readStringConfig(preset, "topic") ?? preset.widget_id;

  return {
    ...preset,
    category,
    description,
    providerDetail: formatProviderDetail(preset, entry),
    refreshDetail: formatRefreshDetail(entry),
    allowedSizes: entry?.manifest.allowed_sizes.join(", ") ?? preset.size,
    sourceDetail,
  };
}

function buildRegistryPresets(registry: Record<string, WidgetRegistryEntry>): CatalogItem[] {
  const presetWidgetIds = new Set(WIDGET_PRESETS.map((preset) => preset.widget_id));
  return Object.values(registry)
    .filter((entry) => isAddableRegistryEntry(entry) && !presetWidgetIds.has(entry.manifest.id))
    .map((entry) =>
      enrichPreset(
        {
          key: `${entry.manifest.id}-default`,
          label: entry.manifest.name,
          widget_id: entry.manifest.id,
          title: entry.manifest.name,
          size: entry.manifest.preferred_size,
          config: {},
        },
        entry,
      ),
    );
}

export function CommandPalette({ open, registry, onClose, onSelect }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const listId = useId();

  const availableWidgetIds = useMemo(
    () =>
      new Set(
        Object.values(registry)
          .filter(isAddableRegistryEntry)
          .map((entry) => entry.manifest.id),
      ),
    [registry],
  );
  const registryById = useMemo(
    () => new Map(Object.values(registry).map((entry) => [entry.manifest.id, entry])),
    [registry],
  );
  const catalog = useMemo(
    () => [
      ...WIDGET_PRESETS.filter((preset) => availableWidgetIds.has(preset.widget_id)).map((preset) =>
        enrichPreset(preset, registryById.get(preset.widget_id)),
      ),
      ...buildRegistryPresets(registry),
    ],
    [availableWidgetIds, registry, registryById],
  );

  const presets = useMemo(() => {
    if (!query) {
      return catalog;
    }
    const needle = query.toLowerCase();
    return catalog.filter(
      (preset) =>
        preset.label.toLowerCase().includes(needle) ||
        preset.title.toLowerCase().includes(needle) ||
        preset.widget_id.toLowerCase().includes(needle) ||
        preset.category.toLowerCase().includes(needle) ||
        preset.description.toLowerCase().includes(needle) ||
        preset.providerDetail.toLowerCase().includes(needle) ||
        preset.refreshDetail.toLowerCase().includes(needle) ||
        preset.allowedSizes.toLowerCase().includes(needle) ||
        preset.sourceDetail.toLowerCase().includes(needle),
    );
  }, [catalog, query]);

  useEffect(() => {
    if (!open) {
      return;
    }
    setQuery("");
    const focusTimer = window.setTimeout(() => searchRef.current?.focus(), 0);
    return () => window.clearTimeout(focusTimer);
  }, [open]);

  function handleSelect(preset: WidgetPreset) {
    onSelect(preset);
    onClose();
  }

  function handleSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter" || event.nativeEvent.isComposing) {
      return;
    }
    const firstPreset = presets[0];
    if (!firstPreset) {
      return;
    }
    event.preventDefault();
    handleSelect(firstPreset);
  }

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-slate-950/78 px-3 py-16 backdrop-blur-md sm:px-4 sm:py-20"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        className="glass-panel-strong accent-border w-full max-w-3xl rounded-[14px] border border-white/10 bg-[#080c10] p-4 shadow-2xl sm:p-5"
      >
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Command box</p>
            <h2 id={titleId} className="mt-1 text-lg font-semibold text-white">
              Add registered widget
            </h2>
            <p id={descriptionId} className="mt-2 text-sm text-slate-400">
              Search approved manifests, provider-backed presets, and niche runtime feeds.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-[8px] border border-white/10 px-3 py-2 text-sm text-slate-300 transition duration-200 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300/70"
          >
            Close
          </button>
        </div>
        <div className="mt-5">
          <label htmlFor={`${listId}-search`} className="sr-only">
            Search widgets
          </label>
          <input
            id={`${listId}-search`}
            ref={searchRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleSearchKeyDown}
            placeholder="Search by widget, category, provider, source..."
            autoComplete="off"
            aria-controls={listId}
            className="w-full rounded-[8px] border border-cyan-300/20 bg-[#05070a] px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500 transition focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-300/20"
          />
        </div>
        <div id={listId} className="mt-4 grid max-h-[min(58vh,560px)] gap-2 overflow-y-auto pr-1">
          {presets.length === 0 ? (
            <div className="rounded-[10px] border border-dashed border-white/12 bg-white/[0.03] p-6 text-center">
              <p className="text-sm font-medium text-white">No preset matched that search.</p>
              <p className="mt-2 text-sm text-slate-400">Try widget ids like news, sports, or countdown.</p>
            </div>
          ) : (
            presets.map((preset) => (
              <button
                key={preset.key}
                type="button"
                onClick={() => handleSelect(preset)}
                className={cn(
                  "group rounded-[10px] border border-white/10 bg-white/[0.035] p-4 text-left transition duration-200",
                  "hover:border-cyan-300/40 hover:bg-cyan-300/10 focus-visible:border-cyan-300/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300/60",
                )}
              >
                <div className="grid gap-3 md:grid-cols-[1fr_auto_auto] md:items-center">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium text-white">{preset.label}</p>
                      <span className="rounded border border-cyan-300/20 bg-cyan-300/8 px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-cyan-100">
                        {preset.category}
                      </span>
                      <span className="rounded border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-slate-400">
                        {preset.size} tile
                      </span>
                    </div>
                    <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-400">{preset.description}</p>
                    <p className="mt-2 text-[11px] uppercase tracking-[0.14em] text-slate-500">
                      {preset.widget_id} / {preset.sourceDetail}
                    </p>
                  </div>
                  <div className="grid gap-2 text-xs text-slate-300 sm:grid-cols-3 md:w-[320px] md:grid-cols-1">
                    <PaletteMetric label="Provider" value={preset.providerDetail} />
                    <PaletteMetric label="Refresh" value={preset.refreshDetail} />
                    <PaletteMetric label="Allowed" value={preset.allowedSizes} />
                  </div>
                  <span className="text-xs font-medium uppercase tracking-[0.16em] text-cyan-100 transition group-hover:text-white">
                    Add widget
                  </span>
                </div>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function PaletteMetric({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex min-w-0 items-center justify-between gap-3 rounded-[8px] border border-white/8 bg-black/20 px-2.5 py-1.5">
      <span className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</span>
      <span className="truncate text-slate-200">{value}</span>
    </span>
  );
}
