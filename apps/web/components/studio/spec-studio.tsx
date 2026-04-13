"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import type { ReactNode } from "react";

import {
  approveGenerationJob,
  createGenerationJob,
  fetchAIProviders,
  fetchGenerationJob,
  fetchGenerationJobs,
  fetchGenerationPreview,
  installGenerationJob,
  previewSpecDocument,
  rejectGenerationJob,
} from "@/lib/api";
import type {
  AIProvider,
  GenerationArtifact,
  GenerationJob,
  GenerationPipelinePreview,
  SpecValidationResult,
} from "@/lib/types";

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
  const [idea, setIdea] = useState("Build a compact operations status widget with refresh health, active alerts, and a short summary.");
  const [reviewNote, setReviewNote] = useState("");
  const [result, setResult] = useState<SpecValidationResult | null>(null);
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>("codex");
  const [generationPreview, setGenerationPreview] = useState<GenerationPipelinePreview | null>(null);
  const [jobHistory, setJobHistory] = useState<GenerationJob[]>([]);
  const [currentJob, setCurrentJob] = useState<GenerationJob | null>(null);
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [validationLoading, setValidationLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;
    void Promise.all([fetchAIProviders(), fetchGenerationJobs()])
      .then(([providerItems, jobItems]) => {
        if (cancelled) {
          return;
        }
        setProviders(providerItems);
        setJobHistory(jobItems);
        if (jobItems[0]) {
          setCurrentJob(jobItems[0]);
        }
        if (providerItems[0] && !providerItems.some((provider) => provider.provider_id === selectedProvider)) {
          setSelectedProvider(providerItems[0].provider_id);
        }
      })
      .catch((loadError) => {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Failed to load AI studio state");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedProvider]);

  useEffect(() => {
    setValidationLoading(true);
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
        .finally(() => setValidationLoading(false));
    }, 450);
    return () => window.clearTimeout(timeout);
  }, [format, payload, providers, selectedProvider]);

  useEffect(() => {
    if (!currentJob || !["queued", "running"].includes(currentJob.status)) {
      return;
    }
    const timeout = window.setTimeout(() => {
      void fetchGenerationJob(currentJob.id)
        .then((job) => {
          setCurrentJob(job);
          setJobHistory((items) => replaceJob(items, job));
        })
        .catch(() => undefined);
    }, 1200);
    return () => window.clearTimeout(timeout);
  }, [currentJob]);

  const highlightedError = result?.errors[0];
  const lines = payload.split("\n");
  const highlightedLine = highlightedError?.line ?? null;
  const selectedProviderDetails = providers.find((provider) => provider.provider_id === selectedProvider) ?? null;
  const fallbackProviders = providers
    .filter((provider) => provider.provider_id !== selectedProvider)
    .map((provider) => provider.provider_id);
  const codeArtifact = useMemo(
    () => currentJob?.artifacts.find((artifact) => artifact.stage === "codegen" && artifact.artifact_type === "package") ?? null,
    [currentJob],
  );
  const files = useMemo(() => codeArtifact?.files ?? [], [codeArtifact]);
  const selectedFile = files.find((file) => file.path === selectedFilePath) ?? files[0] ?? null;

  useEffect(() => {
    if (!selectedFile && files[0]) {
      setSelectedFilePath(files[0].path);
    }
    if (selectedFile && selectedFile.path !== selectedFilePath) {
      setSelectedFilePath(selectedFile.path);
    }
  }, [files, selectedFile, selectedFilePath]);

  const runGeneration = (mode: "idea" | "stage" | "regenerate") => {
    setError(null);
    startTransition(() => {
      const payloadForRequest =
        mode === "idea"
          ? {
              provider_id: selectedProvider,
              fallback_provider_ids: fallbackProviders,
              idea: idea.trim(),
            }
          : mode === "regenerate" && currentJob
            ? {
                provider_id: selectedProvider,
                fallback_provider_ids: fallbackProviders,
                regenerate_from_job_id: currentJob.id,
              }
            : {
                provider_id: selectedProvider,
                fallback_provider_ids: fallbackProviders,
                stage_id: result?.stage_id,
              };

      void createGenerationJob(payloadForRequest)
        .then((job) => {
          setCurrentJob(job);
          setJobHistory((items) => replaceJob(items, job));
          setSelectedFilePath(job.artifacts.find((artifact) => artifact.stage === "codegen")?.files[0]?.path ?? null);
        })
        .catch((requestError) => {
          setError(requestError instanceof Error ? requestError.message : "Generation failed");
        });
    });
  };

  const runReviewAction = (action: "approve" | "reject" | "install") => {
    if (!currentJob) {
      return;
    }
    setError(null);
    startTransition(() => {
      const requestPromise =
        action === "approve"
          ? approveGenerationJob(currentJob.id)
          : action === "reject"
            ? rejectGenerationJob(currentJob.id, reviewNote.trim() || "Rejected from Spec Studio review.")
            : installGenerationJob(currentJob.id);

      void requestPromise
        .then((job) => {
          setCurrentJob(job);
          setJobHistory((items) => replaceJob(items, job));
        })
        .catch((requestError) => {
          setError(requestError instanceof Error ? requestError.message : "Action failed");
        });
    });
  };

  return (
    <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
      <section className="space-y-6">
        <Panel
          eyebrow="Idea"
          title="Natural language entry"
          description="Use an idea prompt or the strict JSON/YAML editor. Both paths stay review-gated."
        >
          <textarea
            value={idea}
            onChange={(event) => setIdea(event.target.value)}
            className="min-h-[120px] w-full rounded-3xl border border-white/10 bg-slate-950/80 p-4 text-sm text-slate-100 outline-none focus:border-cyan-300/40"
            placeholder="Describe the widget idea, data source, and board behavior."
          />
          <div className="mt-4 flex flex-wrap gap-3">
            <button
              type="button"
              disabled={!idea.trim() || isPending || !selectedProviderDetails?.supports_idea_to_spec}
              onClick={() => runGeneration("idea")}
              className="rounded-full border border-cyan-300/30 bg-cyan-300/15 px-4 py-2 text-sm text-cyan-50 transition hover:bg-cyan-300/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isPending ? "Generating..." : "Generate From Idea"}
            </button>
            <span className="rounded-full border border-white/10 px-3 py-2 text-xs uppercase tracking-[0.18em] text-slate-400">
              Provider {selectedProvider}
            </span>
          </div>
        </Panel>

        <Panel
          eyebrow="Draft"
          title="YAML / JSON spec editor"
          description="Validation is live. The studio stages specs, previews manifests, and keeps install blocked until review."
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
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
            <button
              type="button"
              disabled={!result?.valid || isPending}
              onClick={() => runGeneration("stage")}
              className="rounded-full border border-emerald-300/30 bg-emerald-300/15 px-4 py-2 text-sm text-emerald-50 transition hover:bg-emerald-300/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isPending ? "Generating..." : "Generate From Validated Spec"}
            </button>
          </div>
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
              {validationLoading ? "Validating..." : result?.valid ? "Validated for generation" : "Draft needs attention"}
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
        </Panel>
      </section>

      <section className="space-y-6">
        <Panel eyebrow="Validation" title="Spec and manifest preview">
          {!result ? (
            <p className="text-sm text-slate-300">Waiting for the first validation result.</p>
          ) : (
            <div className="space-y-4">
              <PreviewBlock title="Stage">
                <p>{result.stage}</p>
                <p className="mt-1 text-xs text-slate-400">Stage id: {result.stage_id}</p>
              </PreviewBlock>
              <PreviewBlock title="Notes">
                {result.notes.length === 0 ? <p>No blocking notes.</p> : result.notes.map((note) => <p key={note}>{note}</p>)}
              </PreviewBlock>
              <PreviewBlock title="Manifest Preview">
                <JsonBlock value={result.manifest_preview} />
              </PreviewBlock>
              {result.normalized_spec ? (
                <PreviewBlock title="Normalized Spec">
                  <JsonBlock value={result.normalized_spec} />
                </PreviewBlock>
              ) : null}
              <PreviewBlock title="Scaffold Preview">
                {result.scaffold_preview.files.map((file) => (
                  <p key={file}>{file}</p>
                ))}
              </PreviewBlock>
            </div>
          )}
        </Panel>

        <Panel eyebrow="AI Layer" title="Provider adapters and staged execution">
          <div className="flex flex-wrap items-center justify-between gap-3">
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
            {currentJob ? (
              <button
                type="button"
                onClick={() => runGeneration("regenerate")}
                disabled={isPending}
                className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-100 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Regenerate
              </button>
            ) : null}
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
                  Idea→Spec: {String(provider.supports_idea_to_spec)} | Codegen: {String(provider.supports_codegen)} | Review:{" "}
                  {String(provider.supports_review)}
                </p>
              </div>
            ))}
          </div>
          {generationPreview ? (
            <div className="mt-4 rounded-2xl border border-cyan-300/15 bg-cyan-300/10 p-4">
              <p className="text-sm font-medium text-cyan-50">Pipeline preview</p>
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
        </Panel>

        <Panel eyebrow="Widget Forge" title="Generation job, review, and install">
          {!currentJob ? (
            <p className="text-sm text-slate-300">Run a generation job to inspect artifacts, review output, and install through the registry.</p>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-white">{currentJob.widget_id}</p>
                  <p className="text-xs text-slate-400">
                    Artifact v{currentJob.artifact_version} · provider {currentJob.provider_id} · job {currentJob.id}
                  </p>
                </div>
                <StatusBadge status={currentJob.status} />
              </div>

              <PreviewBlock title="Install target">
                <p>
                  {currentJob.install_target?.action === "update" ? "Update installed widget" : "Install new widget"} to{" "}
                  {currentJob.install_target?.next_version ?? currentJob.selected_version}
                </p>
                {currentJob.install_target?.current_version ? (
                  <p className="text-xs text-slate-400">Current version {currentJob.install_target.current_version}</p>
                ) : null}
              </PreviewBlock>

              <div className="rounded-2xl border border-white/10 bg-slate-950/60 p-4">
                <div className="flex flex-wrap gap-3">
                  <button
                    type="button"
                    onClick={() => runReviewAction("approve")}
                    disabled={isPending || currentJob.status !== "review_required"}
                    className="rounded-full border border-emerald-300/30 bg-emerald-300/15 px-4 py-2 text-sm text-emerald-50 transition hover:bg-emerald-300/20 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    onClick={() => runReviewAction("reject")}
                    disabled={isPending || !["review_required", "approved"].includes(currentJob.status)}
                    className="rounded-full border border-rose-300/30 bg-rose-300/15 px-4 py-2 text-sm text-rose-50 transition hover:bg-rose-300/20 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Reject
                  </button>
                  <button
                    type="button"
                    onClick={() => runReviewAction("install")}
                    disabled={isPending || currentJob.status !== "approved"}
                    className="rounded-full border border-cyan-300/30 bg-cyan-300/15 px-4 py-2 text-sm text-cyan-50 transition hover:bg-cyan-300/20 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Install Through Registry
                  </button>
                </div>
                <textarea
                  value={reviewNote}
                  onChange={(event) => setReviewNote(event.target.value)}
                  className="mt-4 min-h-[96px] w-full rounded-2xl border border-white/10 bg-slate-950/80 p-3 text-sm text-slate-100 outline-none focus:border-cyan-300/40"
                  placeholder="Review note or rejection reason."
                />
              </div>

              <PreviewBlock title="Generated files">
                <ArtifactTabs
                  files={files}
                  selectedFilePath={selectedFilePath}
                  onSelect={setSelectedFilePath}
                  selectedContent={selectedFile?.content ?? ""}
                />
              </PreviewBlock>

              <PreviewBlock title="Diff preview before deployment">
                {currentJob.diff_preview.length === 0 ? (
                  <p>No diff available yet.</p>
                ) : (
                  currentJob.diff_preview.map((diffItem) => (
                    <div key={diffItem.path} className="rounded-2xl border border-white/10 bg-black/20 p-3">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-medium text-white">{diffItem.path}</p>
                        <span className="text-[11px] uppercase tracking-[0.16em] text-slate-400">{diffItem.summary}</span>
                      </div>
                      <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap break-all text-[11px] text-slate-300">
                        {diffItem.diff || "No textual diff."}
                      </pre>
                    </div>
                  ))
                )}
              </PreviewBlock>

              <PreviewBlock title="Job logs">
                {currentJob.logs.map((log) => (
                  <div key={log.id} className="rounded-2xl border border-white/10 bg-black/20 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-medium text-white">
                        {log.step} · {log.level}
                      </p>
                      <span className="text-[11px] uppercase tracking-[0.16em] text-slate-400">
                        {new Date(log.created_at).toLocaleString()}
                      </span>
                    </div>
                    <p className="mt-2 text-sm text-slate-300">{log.message}</p>
                  </div>
                ))}
              </PreviewBlock>
            </div>
          )}
        </Panel>

        <Panel eyebrow="History" title="Generation history">
          <div className="space-y-3">
            {jobHistory.length === 0 ? (
              <p className="text-sm text-slate-300">No generation history yet.</p>
            ) : (
              jobHistory.map((job) => (
                <button
                  key={job.id}
                  type="button"
                  onClick={() => setCurrentJob(job)}
                  className={`w-full rounded-2xl border p-4 text-left transition ${
                    currentJob?.id === job.id
                      ? "border-cyan-300/30 bg-cyan-300/10"
                      : "border-white/10 bg-slate-950/60 hover:bg-white/10"
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-white">{job.widget_id}</p>
                      <p className="mt-1 text-xs text-slate-400">
                        {job.provider_id} · artifact v{job.artifact_version} · {job.selected_version}
                      </p>
                    </div>
                    <StatusBadge status={job.status} />
                  </div>
                </button>
              ))
            )}
          </div>
        </Panel>
      </section>
    </div>
  );
}

function Panel({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[28px] border border-white/10 bg-white/5 p-5">
      <p className="text-xs uppercase tracking-[0.24em] text-slate-500">{eyebrow}</p>
      <h2 className="mt-2 text-xl font-semibold text-white">{title}</h2>
      {description ? <p className="mt-2 text-sm text-slate-300">{description}</p> : null}
      <div className="mt-4">{children}</div>
    </section>
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

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="whitespace-pre-wrap break-all text-xs text-slate-300">{JSON.stringify(value, null, 2)}</pre>;
}

function StatusBadge({ status }: { status: GenerationJob["status"] }) {
  const styles =
    status === "installed"
      ? "border-emerald-300/30 bg-emerald-300/15 text-emerald-50"
      : status === "approved"
        ? "border-cyan-300/30 bg-cyan-300/15 text-cyan-50"
        : status === "review_required"
          ? "border-amber-300/30 bg-amber-300/15 text-amber-50"
          : status === "failed" || status === "rejected"
            ? "border-rose-300/30 bg-rose-300/15 text-rose-50"
            : "border-white/10 bg-white/5 text-slate-200";
  return <span className={`rounded-full border px-3 py-1 text-xs uppercase tracking-[0.16em] ${styles}`}>{status}</span>;
}

function ArtifactTabs({
  files,
  selectedFilePath,
  onSelect,
  selectedContent,
}: {
  files: GenerationArtifact["files"];
  selectedFilePath: string | null;
  onSelect: (path: string) => void;
  selectedContent: string;
}) {
  if (files.length === 0) {
    return <p>No generated files yet.</p>;
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {files.map((file) => (
          <button
            key={file.path}
            type="button"
            onClick={() => onSelect(file.path)}
            className={`rounded-full px-3 py-2 text-xs transition ${
              file.path === selectedFilePath
                ? "border border-cyan-300/30 bg-cyan-300/15 text-cyan-50"
                : "border border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
            }`}
          >
            {file.path.split("/").slice(-2).join("/")}
          </button>
        ))}
      </div>
      <pre className="max-h-[420px] overflow-auto rounded-2xl border border-white/10 bg-black/30 p-4 text-[12px] text-slate-200">
        {selectedContent}
      </pre>
    </div>
  );
}

function replaceJob(items: GenerationJob[], nextJob: GenerationJob) {
  const remaining = items.filter((item) => item.id !== nextJob.id);
  return [nextJob, ...remaining];
}
