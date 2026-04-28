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

const workflowStages = [
  { id: "prompt", label: "Prompt" },
  { id: "generate", label: "Generate" },
  { id: "review", label: "Review" },
  { id: "install", label: "Install" },
] as const;

export function SpecStudio() {
  const [format, setFormat] = useState<"json" | "yaml">("json");
  const [payload, setPayload] = useState(defaultJson);
  const [idea, setIdea] = useState("Build a compact operations status widget with refresh health, active alerts, and a short summary.");
  const [reviewNote, setReviewNote] = useState("");
  const [result, setResult] = useState<SpecValidationResult | null>(null);
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>("codex");
  const [selectedModel, setSelectedModel] = useState<string>("");
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
        const activeProvider =
          providerItems.find((provider) => provider.provider_id === selectedProvider) ?? providerItems[0] ?? null;
        if (activeProvider) {
          setSelectedModel(activeProvider.default_model_id ?? activeProvider.supported_model_ids[0] ?? "");
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

  const selectedProviderDetails = providers.find((provider) => provider.provider_id === selectedProvider) ?? null;
  const modelOptions = selectedProviderDetails?.supported_model_ids ?? [];
  const fallbackProviders = providers
    .filter((provider) => provider.provider_id !== selectedProvider)
    .map((provider) => provider.provider_id);
  const highlightedError = result?.errors[0] ?? null;
  const lines = payload.split("\n");
  const highlightedLine = highlightedError?.line ?? null;
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

  const workflowState = {
    prompt: idea.trim() || payload.trim() ? "complete" : "idle",
    generate:
      validationLoading || currentJob?.status === "queued" || currentJob?.status === "running"
        ? "active"
        : currentJob
          ? "complete"
          : result?.valid
            ? "ready"
            : "idle",
    review:
      currentJob?.status === "review_required"
        ? "active"
        : currentJob && ["approved", "installed"].includes(currentJob.status)
          ? "complete"
          : currentJob && ["failed", "rejected"].includes(currentJob.status)
            ? "error"
            : "idle",
    install:
      currentJob?.status === "installed"
        ? "complete"
        : currentJob?.status === "approved"
          ? "ready"
          : currentJob?.status === "failed"
            ? "error"
            : "idle",
  } as const;

  const providerUnavailable = providers.length === 0;
  const generationBlocked = providerUnavailable || !selectedProviderDetails;

  const runGeneration = (mode: "idea" | "stage" | "regenerate") => {
    setError(null);
    startTransition(() => {
      const payloadForRequest =
        mode === "idea"
          ? {
              provider_id: selectedProvider,
              model_id: selectedModel || undefined,
              fallback_provider_ids: fallbackProviders,
              idea: idea.trim(),
            }
          : mode === "regenerate" && currentJob
            ? {
                provider_id: selectedProvider,
                model_id: selectedModel || undefined,
                fallback_provider_ids: fallbackProviders,
                regenerate_from_job_id: currentJob.id,
              }
            : {
                provider_id: selectedProvider,
                model_id: selectedModel || undefined,
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
    <div className="space-y-5">
      <section className="rounded-[24px] border border-white/10 bg-[#090c10] p-5 md:p-6">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <p className="text-[10px] uppercase tracking-[0.24em] text-slate-500">Spec studio</p>
            <h2 className="mt-2 text-2xl font-semibold text-white md:text-3xl">Prompt, generate, review, install</h2>
            <p className="mt-3 text-sm leading-6 text-slate-400">
              Keep the main path short. Raw spec editing, scaffold detail, diffs, and logs stay available, but they do not lead the screen anymore.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <MetricSummary label="Provider" value={selectedProviderDetails?.label ?? "None"} />
            <MetricSummary label="Validation" value={validationLoading ? "Running" : result?.valid ? "Ready" : "Draft"} />
            <MetricSummary label="Current job" value={currentJob?.status ?? "Idle"} />
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-4">
          {workflowStages.map((stage, index) => (
            <WorkflowCard key={stage.id} index={index + 1} label={stage.label} state={workflowState[stage.id]} />
          ))}
        </div>
      </section>

      {error ? (
        <div className="rounded-[18px] border border-rose-300/18 bg-rose-300/8 px-4 py-3 text-sm text-rose-50">
          <p className="text-[10px] uppercase tracking-[0.18em] text-rose-200/80">Studio warning</p>
          <p className="mt-1">{error}</p>
        </div>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
        <section className="space-y-5">
          <Panel
            eyebrow="Step 1"
            title="Prompt"
            description="Describe the widget in plain language, then choose which provider should stage the spec and code generation pass."
          >
            <textarea
              value={idea}
              onChange={(event) => setIdea(event.target.value)}
              className="min-h-[160px] w-full rounded-[18px] border border-white/10 bg-[#07090d] p-4 text-sm leading-6 text-slate-100 outline-none transition focus:border-cyan-300/30"
              placeholder="Describe the widget idea, expected data source, and board behavior."
            />

            <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] md:items-center">
              <label className="grid gap-2">
                <span className="text-xs uppercase tracking-[0.16em] text-slate-500">Provider</span>
                <select
                  value={selectedProvider}
                  onChange={(event) => {
                    const providerId = event.target.value;
                    const provider = providers.find((item) => item.provider_id === providerId);
                    setSelectedProvider(providerId);
                    setSelectedModel(provider?.default_model_id ?? provider?.supported_model_ids[0] ?? "");
                  }}
                  className="rounded-[14px] border border-white/10 bg-[#07090d] px-3 py-2 text-sm text-slate-100 outline-none"
                >
                  {providers.map((provider) => (
                    <option key={provider.provider_id} value={provider.provider_id}>
                      {provider.label}
                    </option>
                  ))}
                </select>
              </label>

              {modelOptions.length > 0 ? (
                <label className="grid gap-2">
                  <span className="text-xs uppercase tracking-[0.16em] text-slate-500">Model</span>
                  <select
                    value={selectedModel}
                    onChange={(event) => setSelectedModel(event.target.value)}
                    className="rounded-[14px] border border-white/10 bg-[#07090d] px-3 py-2 text-sm text-slate-100 outline-none"
                  >
                    {modelOptions.map((modelId) => (
                      <option key={modelId} value={modelId}>
                        {modelId}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}

              <ActionButton
                onClick={() => runGeneration("idea")}
                disabled={!idea.trim() || isPending || generationBlocked || !selectedProviderDetails?.supports_idea_to_spec}
                tone="primary"
              >
                {isPending ? "Generating..." : "Generate"}
              </ActionButton>

              {currentJob ? (
                <ActionButton onClick={() => runGeneration("regenerate")} disabled={isPending || generationBlocked}>
                  Regenerate
                </ActionButton>
              ) : null}
            </div>

            {providerUnavailable ? (
              <InlineNotice title="No providers available" body="Open System Panel to enable or configure at least one AI provider before generation." tone="warning" />
            ) : null}
          </Panel>

          <Panel
            eyebrow="Step 2"
            title="Generate"
            description="A valid staged spec can generate from the editor path as well. Validation runs in the background while you edit."
          >
            <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-center">
              <div className="rounded-[16px] border border-white/10 bg-[#07090d] px-4 py-3">
                <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Validation state</p>
                <p className="mt-2 text-sm font-medium text-white">
                  {validationLoading ? "Validating draft..." : result?.valid ? "Draft is ready for generation." : "Draft needs attention."}
                </p>
                {result?.stage_id ? <p className="mt-1 text-xs text-slate-400">Stage {result.stage_id}</p> : null}
              </div>
              <ActionButton onClick={() => runGeneration("stage")} disabled={!result?.valid || isPending || generationBlocked} tone="success">
                {isPending ? "Generating..." : "Generate From Spec"}
              </ActionButton>
            </div>

            {generationPreview ? (
              <div className="mt-4 grid gap-2">
                {generationPreview.steps.map((step) => (
                  <div key={step.id} className="flex items-center justify-between gap-3 rounded-[14px] border border-white/10 bg-[#07090d] px-3 py-2 text-sm text-slate-200">
                    <span>{step.label}</span>
                    <span className="rounded border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-slate-400">
                      {step.status}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}

            {highlightedError ? (
              <div className="mt-4 rounded-[16px] border border-rose-300/18 bg-rose-300/8 p-4">
                <p className="text-sm font-medium text-rose-50">{highlightedError.message}</p>
                <p className="mt-1 text-xs text-rose-100/80">
                  {highlightedError.line ? `Line ${highlightedError.line}` : "Validation detail"}
                  {highlightedError.column ? `, column ${highlightedError.column}` : ""}
                </p>
              </div>
            ) : null}
          </Panel>

          <CollapsiblePanel eyebrow="Advanced" title="Spec editor and validation detail">
            <div className="flex flex-wrap gap-2">
              {(["json", "yaml"] as const).map((nextFormat) => (
                <button
                  key={nextFormat}
                  type="button"
                  onClick={() => {
                    setFormat(nextFormat);
                    setPayload(nextFormat === "json" ? defaultJson : defaultYaml);
                  }}
                  className={`rounded-[10px] border px-3 py-2 text-xs uppercase tracking-[0.14em] transition ${
                    format === nextFormat
                      ? "border-cyan-300/20 bg-cyan-300/10 text-cyan-50"
                      : "border-white/10 bg-white/[0.04] text-slate-300 hover:bg-white/[0.08]"
                  }`}
                >
                  {nextFormat}
                </button>
              ))}
            </div>

            <textarea
              value={payload}
              onChange={(event) => setPayload(event.target.value)}
              className={`mt-4 min-h-[360px] w-full rounded-[18px] border border-white/10 bg-[#07090d] p-4 font-mono text-sm leading-6 outline-none ${
                result?.errors.length ? "text-rose-50" : "text-slate-100"
              }`}
            />

            {highlightedError ? (
              <div className="mt-4 space-y-1 rounded-[16px] border border-white/10 bg-[#07090d] p-3 font-mono text-xs">
                {lines
                  .slice(Math.max((highlightedLine ?? 1) - 3, 0), Math.min((highlightedLine ?? 1) + 2, lines.length))
                  .map((line, index) => {
                    const actualLine = Math.max((highlightedLine ?? 1) - 2, 1) + index;
                    return (
                      <div
                        key={`${actualLine}-${line}`}
                        className={`rounded px-3 py-1.5 ${
                          actualLine === highlightedLine ? "bg-rose-300/10 text-rose-50" : "text-slate-300"
                        }`}
                      >
                        <span className="mr-3 text-slate-500">{String(actualLine).padStart(3, "0")}</span>
                        {line || " "}
                      </div>
                    );
                  })}
              </div>
            ) : null}

            <div className="mt-4 grid gap-4">
              <PreviewBlock title="Manifest preview">
                <JsonBlock value={result?.manifest_preview ?? null} />
              </PreviewBlock>
              {result?.normalized_spec ? (
                <PreviewBlock title="Normalized spec">
                  <JsonBlock value={result.normalized_spec} />
                </PreviewBlock>
              ) : null}
              <PreviewBlock title="Scaffold preview">
                <div className="grid gap-2">
                  {(result?.scaffold_preview.files ?? []).map((file) => (
                    <div key={file} className="rounded-[12px] border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-slate-300">
                      {file}
                    </div>
                  ))}
                </div>
              </PreviewBlock>
            </div>
          </CollapsiblePanel>
        </section>

        <section className="space-y-5">
          <Panel
            eyebrow="Step 3"
            title="Review"
            description="Review stays explicit. Generated output must move through approval before installation is unlocked."
          >
            {!currentJob ? (
              <EmptyState
                title="No generation job yet"
                body="Run generation from the prompt or validated spec to inspect staged artifacts."
              />
            ) : (
              <div className="space-y-4">
                <div className="flex items-center justify-between gap-3 rounded-[16px] border border-white/10 bg-[#07090d] px-4 py-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-white">{currentJob.widget_id}</p>
                    <p className="mt-1 text-xs text-slate-400">
                      Provider {currentJob.provider_id} · Artifact v{currentJob.artifact_version}
                    </p>
                  </div>
                  <StatusBadge status={currentJob.status} />
                </div>

                <div className="rounded-[16px] border border-white/10 bg-[#07090d] p-4">
                  <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Install target</p>
                  <p className="mt-2 text-sm text-white">
                    {currentJob.install_target?.action === "update" ? "Update installed widget" : "Install new widget"} to{" "}
                    {currentJob.install_target?.next_version ?? currentJob.selected_version}
                  </p>
                  {currentJob.install_target?.current_version ? (
                    <p className="mt-1 text-xs text-slate-400">Current version {currentJob.install_target.current_version}</p>
                  ) : null}
                </div>

                <div className="grid gap-2 sm:grid-cols-3">
                  <ActionButton
                    onClick={() => runReviewAction("approve")}
                    disabled={isPending || currentJob.status !== "review_required"}
                    tone="success"
                  >
                    Approve
                  </ActionButton>
                  <ActionButton
                    onClick={() => runReviewAction("reject")}
                    disabled={isPending || !["review_required", "approved"].includes(currentJob.status)}
                    tone="danger"
                  >
                    Reject
                  </ActionButton>
                  <ActionButton
                    onClick={() => runReviewAction("install")}
                    disabled={isPending || currentJob.status !== "approved"}
                    tone="primary"
                  >
                    Install
                  </ActionButton>
                </div>

                <textarea
                  value={reviewNote}
                  onChange={(event) => setReviewNote(event.target.value)}
                  className="min-h-[110px] w-full rounded-[18px] border border-white/10 bg-[#07090d] p-3 text-sm text-slate-100 outline-none transition focus:border-cyan-300/30"
                  placeholder="Optional review note or rejection reason."
                />
              </div>
            )}
          </Panel>

          <Panel
            eyebrow="Step 4"
            title="Install readiness"
            description="Generated code stays readable here. Full diffs and logs are still available, but secondary."
          >
            {!currentJob ? (
              <EmptyState title="Nothing staged" body="Generate a widget first to inspect the code package and install readiness." />
            ) : (
              <div className="space-y-4">
                <PreviewBlock title="Generated files">
                  <ArtifactTabs
                    files={files}
                    selectedFilePath={selectedFilePath}
                    onSelect={setSelectedFilePath}
                    selectedContent={selectedFile?.content ?? ""}
                  />
                </PreviewBlock>

                {currentJob.diff_preview.length > 0 ? (
                  <PreviewBlock title="Diff summary">
                    <div className="grid gap-2">
                      {currentJob.diff_preview.map((diffItem) => (
                        <div key={diffItem.path} className="rounded-[12px] border border-white/10 bg-white/[0.03] px-3 py-2">
                          <p className="text-sm font-medium text-white">{diffItem.path}</p>
                          <p className="mt-1 text-xs text-slate-400">{diffItem.summary}</p>
                        </div>
                      ))}
                    </div>
                  </PreviewBlock>
                ) : null}
              </div>
            )}
          </Panel>

          <CollapsiblePanel eyebrow="Advanced" title="Providers, full diffs, and logs">
            <div className="grid gap-3">
              {providers.map((provider) => (
                <div key={provider.provider_id} className="rounded-[16px] border border-white/10 bg-[#07090d] p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-white">{provider.label}</p>
                      <p className="mt-1 text-xs text-slate-400">{provider.provider_id}</p>
                    </div>
                    <span className="rounded border border-white/10 px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-slate-300">
                      {provider.status}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <CapabilityPill enabled={provider.supports_idea_to_spec} label="Idea to Spec" />
                    <CapabilityPill enabled={provider.supports_codegen} label="Codegen" />
                    <CapabilityPill enabled={provider.supports_review} label="Review" />
                  </div>
                </div>
              ))}
            </div>

            {currentJob?.diff_preview.length ? (
              <div className="mt-4 space-y-3">
                {currentJob.diff_preview.map((diffItem) => (
                  <div key={diffItem.path} className="overflow-hidden rounded-[16px] border border-white/10 bg-[#07090d]">
                    <div className="flex items-center justify-between gap-3 px-4 py-3">
                      <p className="text-sm font-medium text-white">{diffItem.path}</p>
                      <span className="text-[10px] uppercase tracking-[0.14em] text-slate-400">{diffItem.summary}</span>
                    </div>
                    <pre className="max-h-52 overflow-auto border-t border-white/10 px-4 py-3 whitespace-pre-wrap break-all text-[11px] text-slate-300">
                      {diffItem.diff || "No textual diff."}
                    </pre>
                  </div>
                ))}
              </div>
            ) : null}

            {currentJob?.logs.length ? (
              <div className="mt-4 space-y-3">
                {currentJob.logs.map((log) => (
                  <div key={log.id} className="rounded-[16px] border border-white/10 bg-[#07090d] p-4">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-medium text-white">
                        {log.step} · {log.level}
                      </p>
                      <span className="text-[10px] uppercase tracking-[0.14em] text-slate-400">
                        {new Date(log.created_at).toLocaleString()}
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-300">{log.message}</p>
                  </div>
                ))}
              </div>
            ) : null}
          </CollapsiblePanel>

          <Panel eyebrow="History" title="Recent jobs">
            <div className="space-y-2">
              {jobHistory.length === 0 ? (
                <EmptyState title="No generation history" body="Successful and failed jobs will collect here after the first run." />
              ) : (
                jobHistory.map((job) => (
                  <button
                    key={job.id}
                    type="button"
                    onClick={() => setCurrentJob(job)}
                    className={`w-full rounded-[16px] border px-4 py-3 text-left transition ${
                      currentJob?.id === job.id
                        ? "border-cyan-300/20 bg-cyan-300/8"
                        : "border-white/10 bg-[#07090d] hover:bg-white/[0.05]"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-white">{job.widget_id}</p>
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
    <section className="rounded-[24px] border border-white/10 bg-[#090c10] p-5">
      <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">{eyebrow}</p>
      <h2 className="mt-2 text-xl font-semibold text-white">{title}</h2>
      {description ? <p className="mt-2 text-sm leading-6 text-slate-400">{description}</p> : null}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function CollapsiblePanel({ eyebrow, title, children }: { eyebrow: string; title: string; children: ReactNode }) {
  return (
    <details className="rounded-[24px] border border-white/10 bg-[#090c10]">
      <summary className="cursor-pointer list-none px-5 py-4">
        <span className="block text-[10px] uppercase tracking-[0.2em] text-slate-500">{eyebrow}</span>
        <span className="mt-2 block text-lg font-semibold text-white">{title}</span>
      </summary>
      <div className="border-t border-white/10 px-5 py-4">{children}</div>
    </details>
  );
}

function PreviewBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-[16px] border border-white/10 bg-[#07090d] p-4">
      <p className="mb-3 text-sm font-medium text-white">{title}</p>
      <div className="space-y-2 text-sm leading-6 text-slate-300">{children}</div>
    </div>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="overflow-auto rounded-[14px] border border-white/10 bg-black/20 p-4 whitespace-pre-wrap break-all text-xs leading-6 text-slate-300">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
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
    return <EmptyState title="No generated files yet" body="Generated package contents appear here after codegen finishes." compact />;
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {files.map((file) => (
          <button
            key={file.path}
            type="button"
            onClick={() => onSelect(file.path)}
            className={`rounded-[10px] border px-3 py-2 text-xs transition ${
              file.path === selectedFilePath
                ? "border-cyan-300/20 bg-cyan-300/10 text-cyan-50"
                : "border-white/10 bg-white/[0.04] text-slate-300 hover:bg-white/[0.08]"
            }`}
          >
            {file.path.split("/").slice(-2).join("/")}
          </button>
        ))}
      </div>
      <pre className="max-h-[420px] overflow-auto rounded-[16px] border border-white/10 bg-black/20 p-4 text-[12px] leading-6 text-slate-200">
        {selectedContent}
      </pre>
    </div>
  );
}

function MetricSummary({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[16px] border border-white/10 bg-[#07090d] px-4 py-3">
      <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <p className="mt-2 truncate text-sm font-medium text-white">{value}</p>
    </div>
  );
}

function WorkflowCard({
  index,
  label,
  state,
}: {
  index: number;
  label: string;
  state: "idle" | "ready" | "active" | "complete" | "error";
}) {
  const styles =
    state === "complete"
      ? "border-emerald-300/18 bg-emerald-300/8"
      : state === "active"
        ? "border-cyan-300/20 bg-cyan-300/8"
        : state === "ready"
          ? "border-white/10 bg-white/[0.04]"
          : state === "error"
            ? "border-rose-300/18 bg-rose-300/8"
            : "border-white/10 bg-[#07090d]";

  return (
    <div className={`rounded-[16px] border px-4 py-3 ${styles}`}>
      <div className="flex items-center justify-between gap-3">
        <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{String(index).padStart(2, "0")}</span>
        <span className="rounded border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-slate-300">
          {state}
        </span>
      </div>
      <p className="mt-3 text-sm font-medium text-white">{label}</p>
    </div>
  );
}

function ActionButton({
  children,
  onClick,
  disabled,
  tone = "default",
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  tone?: "default" | "primary" | "success" | "danger";
}) {
  const toneClass =
    tone === "primary"
      ? "border-cyan-300/20 bg-cyan-300/10 text-cyan-50 hover:bg-cyan-300/16"
      : tone === "success"
        ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-50 hover:bg-emerald-300/16"
        : tone === "danger"
          ? "border-rose-300/20 bg-rose-300/10 text-rose-50 hover:bg-rose-300/16"
          : "border-white/10 bg-white/[0.04] text-slate-100 hover:bg-white/[0.08]";

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded-[12px] border px-4 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-50 ${toneClass}`}
    >
      {children}
    </button>
  );
}

function StatusBadge({ status }: { status: GenerationJob["status"] }) {
  const styles =
    status === "installed"
      ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-50"
      : status === "approved"
        ? "border-cyan-300/20 bg-cyan-300/10 text-cyan-50"
        : status === "review_required"
          ? "border-amber-300/20 bg-amber-300/10 text-amber-50"
          : status === "failed" || status === "rejected"
            ? "border-rose-300/20 bg-rose-300/10 text-rose-50"
            : "border-white/10 bg-white/[0.04] text-slate-200";
  return <span className={`rounded-[10px] border px-3 py-1 text-xs uppercase tracking-[0.14em] ${styles}`}>{status}</span>;
}

function CapabilityPill({ enabled, label }: { enabled: boolean; label: string }) {
  return (
    <span
      className={`rounded-[10px] border px-3 py-1 text-[11px] uppercase tracking-[0.14em] ${
        enabled ? "border-emerald-300/18 bg-emerald-300/10 text-emerald-50" : "border-white/10 bg-white/[0.04] text-slate-300"
      }`}
    >
      {label}
    </span>
  );
}

function InlineNotice({
  title,
  body,
  tone = "default",
}: {
  title: string;
  body: string;
  tone?: "default" | "warning";
}) {
  return (
    <div
      className={`mt-4 rounded-[16px] border px-4 py-3 ${
        tone === "warning" ? "border-amber-300/18 bg-amber-300/8 text-amber-50" : "border-white/10 bg-white/[0.04] text-slate-200"
      }`}
    >
      <p className="text-sm font-medium">{title}</p>
      <p className={`mt-1 text-sm leading-6 ${tone === "warning" ? "text-amber-50/80" : "text-slate-400"}`}>{body}</p>
    </div>
  );
}

function EmptyState({
  title,
  body,
  compact = false,
}: {
  title: string;
  body: string;
  compact?: boolean;
}) {
  return (
    <div className={`rounded-[16px] border border-dashed border-white/12 bg-white/[0.03] text-center ${compact ? "p-4" : "p-5"}`}>
      <p className="text-sm font-medium text-white">{title}</p>
      <p className="mt-2 text-sm leading-6 text-slate-400">{body}</p>
    </div>
  );
}

function replaceJob(items: GenerationJob[], nextJob: GenerationJob) {
  const remaining = items.filter((item) => item.id !== nextJob.id);
  return [nextJob, ...remaining];
}
