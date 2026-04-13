"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { fetchAIProviders, fetchGenerationPreview, previewSpecDocument } from "@/lib/api";
import type { AIProvider, GenerationPipelinePreview, SpecValidationResult } from "@/lib/types";

const defaultSpec = {
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
};

const defaultJson = JSON.stringify(defaultSpec, null, 2);
const defaultYaml = `id: custom_widget
name: Custom Widget
category: custom
description: Describe the behavior of the widget here.
min_size: 2x2
preferred_size: 4x2
refresh_policy:
  mode: interval
  interval_seconds: 300
source_type: api
permissions:
  - network
output_schema:
  primary: headline
  secondary: status
renderer_type: card
lifecycle_policy:
  expires: false
  stateful: true
`;

export function SpecStudio() {
  const [format, setFormat] = useState<"json" | "yaml">("json");
  const [payload, setPayload] = useState(defaultJson);
  const [result, setResult] = useState<SpecValidationResult | null>(null);
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>("codex");
  const [generationPreview, setGenerationPreview] = useState<GenerationPipelinePreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchAIProviders().then((items) => {
      if (!cancelled) {
        setProviders(items);
        if (items[0] && !items.some((provider) => provider.provider_id === selectedProvider)) {
          setSelectedProvider(items[0].provider_id);
        }
      }
    });
    return () => {
      cancelled = true;
    };
  }, [selectedProvider]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const timeout = window.setTimeout(() => {
      void previewSpecDocument({ format, content: payload })
        .then((response) => {
          setResult(response);
          if (response.valid && response.stage_id && providers.some((provider) => provider.provider_id === selectedProvider)) {
            return fetchGenerationPreview({ stageId: response.stage_id, providerId: selectedProvider }).then(
              setGenerationPreview,
            );
          }
          setGenerationPreview(null);
          return undefined;
        })
        .catch((previewError) => {
          setError(previewError instanceof Error ? previewError.message : "Validation failed");
        })
        .finally(() => setLoading(false));
    }, 450);
    return () => window.clearTimeout(timeout);
  }, [format, payload, providers, selectedProvider]);

  const highlightedError = result?.errors[0];
  const lines = payload.split("\n");
  const highlightedLine = highlightedError?.line ?? null;

  return (
    <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
      <section className="rounded-[28px] border border-white/10 bg-white/5 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Draft</p>
            <h2 className="mt-2 text-xl font-semibold text-white">YAML / JSON spec editor</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            {(["json", "yaml"] as const).map((nextFormat) => (
              <button
                key={nextFormat}
                type="button"
                onClick={() => {
                  setFormat(nextFormat);
                  setPayload(nextFormat === "json" ? defaultJson : defaultYaml);
                }}
                className={`rounded-full px-3 py-2 text-xs uppercase tracking-[0.18em] transition ${
                  format === nextFormat
                    ? "border border-cyan-300/30 bg-cyan-300/15 text-cyan-50"
                    : "border border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
                }`}
              >
                {nextFormat}
              </button>
            ))}
          </div>
        </div>
        <p className="mt-2 text-sm text-slate-300">
          Validation is live. The studio stages drafts, previews manifests and scaffold files, and keeps install blocked.
        </p>
        <textarea
          value={payload}
          onChange={(event) => setPayload(event.target.value)}
          className={`mt-4 min-h-[420px] w-full rounded-3xl border p-4 font-mono text-sm outline-none ${
            result?.errors.length
              ? "border-rose-400/40 bg-rose-400/5 text-rose-50"
              : "border-white/10 bg-slate-950/80 text-slate-100 focus:border-cyan-300/40"
          }`}
        />
        <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
          <span className="rounded-full border border-white/10 px-3 py-1 text-slate-300">
            {loading ? "Validating..." : result?.valid ? "Ready for scaffold review" : "Draft needs attention"}
          </span>
          {error ? <span className="text-rose-300">{error}</span> : null}
        </div>
        {highlightedError ? (
          <div className="mt-4 rounded-3xl border border-rose-400/20 bg-rose-400/10 p-4">
            <p className="text-sm font-medium text-rose-100">Highlighted error</p>
            <p className="mt-1 text-sm text-rose-100">
              {highlightedError.message}
              {highlightedError.line ? ` at line ${highlightedError.line}` : ""}
              {highlightedError.column ? `, column ${highlightedError.column}` : ""}
            </p>
            <div className="mt-3 space-y-1 font-mono text-xs">
              {lines
                .slice(Math.max((highlightedLine ?? 1) - 3, 0), Math.min((highlightedLine ?? 1) + 2, lines.length))
                .map((line, index) => {
                  const actualLine = Math.max((highlightedLine ?? 1) - 2, 1) + index;
                  return (
                    <div
                      key={`${actualLine}-${line}`}
                      className={`rounded-lg px-3 py-1 ${
                        actualLine === highlightedLine ? "bg-rose-400/20 text-rose-50" : "text-slate-300"
                      }`}
                    >
                      <span className="mr-3 text-slate-500">{String(actualLine).padStart(3, "0")}</span>
                      {line || " "}
                    </div>
                  );
                })}
            </div>
          </div>
        ) : null}
      </section>

      <section className="space-y-6">
        <div className="rounded-[28px] border border-white/10 bg-white/5 p-5">
          <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Validation</p>
          <h2 className="mt-2 text-xl font-semibold text-white">Spec and manifest preview</h2>
          {!result ? (
            <p className="mt-4 text-sm text-slate-300">Waiting for the first validation result.</p>
          ) : (
            <div className="mt-4 space-y-4">
              <PreviewBlock title="Stage">
                <p>{result.stage}</p>
                <p className="mt-1 text-xs text-slate-400">Stage id: {result.stage_id}</p>
              </PreviewBlock>
              <PreviewBlock title="Notes">
                {result.notes.length === 0 ? (
                  <p>No blocking notes.</p>
                ) : (
                  result.notes.map((note) => <p key={note}>{note}</p>)
                )}
              </PreviewBlock>
              <PreviewBlock title="Manifest Preview">
                <pre className="whitespace-pre-wrap break-all text-xs text-slate-300">
                  {JSON.stringify(result.manifest_preview, null, 2)}
                </pre>
              </PreviewBlock>
              {result.normalized_spec ? (
                <PreviewBlock title="Normalized Spec">
                  <pre className="whitespace-pre-wrap break-all text-xs text-slate-300">
                    {JSON.stringify(result.normalized_spec, null, 2)}
                  </pre>
                </PreviewBlock>
              ) : null}
              <PreviewBlock title="Scaffold Preview">
                {result.scaffold_preview.files.map((file) => (
                  <p key={file}>{file}</p>
                ))}
              </PreviewBlock>
            </div>
          )}
        </div>

        <div className="rounded-[28px] border border-white/10 bg-white/5 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-slate-500">AI Layer</p>
              <h2 className="mt-2 text-xl font-semibold text-white">Provider adapters</h2>
            </div>
            <select
              value={selectedProvider}
              onChange={(event) => setSelectedProvider(event.target.value)}
              className="rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 outline-none"
            >
              {providers.map((provider) => (
                <option key={provider.provider_id} value={provider.provider_id}>
                  {provider.label}
                </option>
              ))}
            </select>
          </div>
          <div className="mt-4 grid gap-3">
            {providers.map((provider) => (
              <div key={provider.provider_id} className="rounded-2xl border border-white/10 bg-slate-950/60 p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium text-white">{provider.label}</p>
                  <span className="rounded-full border border-white/10 px-2 py-1 text-[11px] uppercase tracking-[0.16em] text-slate-300">
                    {provider.status}
                  </span>
                </div>
                <p className="mt-2 text-xs text-slate-400">
                  Codegen: {String(provider.supports_codegen)} | Review: {String(provider.supports_review)}
                </p>
              </div>
            ))}
          </div>
          {generationPreview ? (
            <div className="mt-4 rounded-2xl border border-cyan-300/15 bg-cyan-300/10 p-4">
              <p className="text-sm font-medium text-cyan-50">Generation pipeline preview</p>
              <div className="mt-3 space-y-2 text-sm text-cyan-50">
                {generationPreview.steps.map((step) => (
                  <div key={step.id} className="flex items-center justify-between gap-4">
                    <span>{step.label}</span>
                    <span className="rounded-full border border-cyan-100/20 px-2 py-0.5 text-[11px] uppercase tracking-[0.16em]">
                      {step.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function PreviewBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-950/70 p-4 text-sm text-slate-200">
      <p className="mb-2 text-sm font-medium text-white">{title}</p>
      <div className="space-y-2 text-sm text-slate-300">{children}</div>
    </div>
  );
}
