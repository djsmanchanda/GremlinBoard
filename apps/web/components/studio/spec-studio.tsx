"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import type { ReactNode } from "react";

import {
  approveGenerationJob,
  createEasyGenerationJob,
  createGenerationJob,
  fetchAIProviders,
  fetchEasyGenerationJob,
  fetchGenerationJob,
  fetchGenerationJobs,
  fetchGenerationPreview,
  installGenerationJob,
  previewSpecDocument,
  rejectGenerationJob,
  submitGenerationFeedback,
} from "@/lib/api";
import type {
  AIProvider,
  GenerationArtifact,
  GenerationJob,
  GenerationPipelinePreview,
  GenerationTestBox,
  JsonObject,
  SpecValidationResult,
  TileSize,
} from "@/lib/types";

const allowedWidgetSizes = ["1x1", "1x2", "2x2", "4x2", "2x4", "4x4"] as const satisfies TileSize[];

type FeedbackCategoryId = "name" | "sizing" | "ui" | "feature";

const feedbackCategories: Array<{ id: FeedbackCategoryId; label: string; description: string }> = [
  { id: "name", label: "Name", description: "Title, identity, category, and wording." },
  { id: "sizing", label: "Sizing", description: "Strict grid footprint and density changes." },
  { id: "ui", label: "UI", description: "Visual hierarchy, layout, and renderer polish." },
  { id: "feature", label: "Feature", description: "Behavior, data, parameters, and state." },
];

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
  const [easyFeedback, setEasyFeedback] = useState("");
  const [feedbackCategory, setFeedbackCategory] = useState<string | null>(null);
  const [lastFeedback, setLastFeedback] = useState<string | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [result, setResult] = useState<SpecValidationResult | null>(null);
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>("codex");
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [generationPreview, setGenerationPreview] = useState<GenerationPipelinePreview | null>(null);
  const [jobHistory, setJobHistory] = useState<GenerationJob[]>([]);
  const [currentJob, setCurrentJob] = useState<GenerationJob | null>(null);
  const [currentTestBox, setCurrentTestBox] = useState<GenerationTestBox | null>(null);
  const [easyJobId, setEasyJobId] = useState<string | null>(null);
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
      if (easyJobId === currentJob.id) {
        void fetchEasyGenerationJob(currentJob.id)
          .then((response) => {
            setCurrentJob(response.job);
            setCurrentTestBox(response.test_box ?? null);
            setJobHistory((items) => replaceJob(items, response.job));
          })
          .catch(() => undefined);
        return;
      }

      void fetchGenerationJob(currentJob.id)
        .then((job) => {
          setCurrentJob(job);
          setJobHistory((items) => replaceJob(items, job));
        })
        .catch(() => undefined);
    }, 1200);
    return () => window.clearTimeout(timeout);
  }, [currentJob, easyJobId]);

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
  const manifestArtifact = useMemo(
    () => currentTestBox?.manifest ?? findArtifactPayload(currentJob, ["manifest", "manifest_preview"]),
    [currentJob, currentTestBox],
  );
  const specArtifact = useMemo(() => findArtifactPayload(currentJob, ["spec", "normalized_spec", "spec_draft"]), [currentJob]);
  const sampleState = useMemo(
    () => currentTestBox?.initial_state ?? buildSampleState(currentJob, manifestArtifact, specArtifact),
    [currentJob, currentTestBox, manifestArtifact, specArtifact],
  );
  const widgetBrief = useMemo(
    () => buildWidgetBrief(currentJob, manifestArtifact, specArtifact, currentTestBox),
    [currentJob, currentTestBox, manifestArtifact, specArtifact],
  );
  const files = useMemo(() => currentTestBox?.files ?? codeArtifact?.files ?? [], [codeArtifact, currentTestBox]);
  const selectedFile = files.find((file) => file.path === selectedFilePath) ?? files[0] ?? null;
  const normalizedFeedbackCategory = normalizeFeedbackCategory(feedbackCategory);

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
      if (mode === "idea") {
        void createEasyGenerationJob({
          provider_id: selectedProvider,
          model_id: selectedModel || undefined,
          fallback_provider_ids: fallbackProviders,
          idea: idea.trim(),
        })
          .then((response) => {
            setCurrentJob(response.job);
            setCurrentTestBox(response.test_box ?? null);
            setEasyJobId(response.job.id);
            setFeedbackCategory(null);
            setJobHistory((items) => replaceJob(items, response.job));
            setSelectedFilePath(response.test_box?.files[0]?.path ?? null);
          })
          .catch((requestError) => {
            setError(requestError instanceof Error ? requestError.message : "Easy generation failed");
          });
        return;
      }

      const payloadForRequest =
        mode === "regenerate" && currentJob
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
          setCurrentTestBox(null);
          setEasyJobId(mode === "regenerate" ? job.id : null);
          setFeedbackCategory(null);
          setJobHistory((items) => replaceJob(items, job));
          setSelectedFilePath(job.artifacts.find((artifact) => artifact.stage === "codegen")?.files[0]?.path ?? null);
        })
        .catch((requestError) => {
          setError(requestError instanceof Error ? requestError.message : "Generation failed");
        });
    });
  };

  const submitFeedback = () => {
    if (!currentJob || !easyFeedback.trim()) {
      return;
    }
    setError(null);
    startTransition(() => {
      void submitGenerationFeedback(currentJob.id, {
        feedback: easyFeedback.trim(),
        provider_id: selectedProvider,
        model_id: selectedModel || undefined,
        fallback_provider_ids: fallbackProviders,
      })
        .then((response) => {
          setLastFeedback(easyFeedback.trim());
          setFeedbackCategory(response.category);
          setEasyFeedback("");
          setCurrentJob(response.job);
          setCurrentTestBox(response.test_box ?? null);
          setEasyJobId(response.job.id);
          setJobHistory((items) => replaceJob(items, response.job));
          setSelectedFilePath(
            response.test_box?.files[0]?.path ?? response.job.artifacts.find((artifact) => artifact.stage === "codegen")?.files[0]?.path ?? null,
          );
        })
        .catch((requestError) => {
          setError(requestError instanceof Error ? requestError.message : "Feedback refinement failed");
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
          setCurrentTestBox(null);
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

      <section className="rounded-[24px] border border-cyan-300/14 bg-[#081016] p-5 md:p-6">
        <div className="space-y-5">
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
            <div>
              <p className="text-[10px] uppercase tracking-[0.22em] text-cyan-100/60">Easy generation</p>
              <h2 className="mt-2 text-2xl font-semibold text-white">Idea to testable widget draft</h2>
              <p className="mt-2 text-sm leading-6 text-slate-400">
                Enter only the widget idea. The agent proposes name, parameters, strict grid size, manifest, renderer package, and sample state before the draft can move to review or install.
              </p>

              <textarea
                value={idea}
                onChange={(event) => setIdea(event.target.value)}
                className="mt-4 min-h-[150px] w-full rounded-[18px] border border-white/10 bg-[#07090d] p-4 text-sm leading-6 text-slate-100 outline-none transition focus:border-cyan-300/30"
                placeholder="Describe the widget idea, expected data source, and board behavior."
              />
            </div>

            <div className="rounded-[18px] border border-white/10 bg-[#07090d] p-4">
              <p className="text-sm font-medium text-white">Strict size choices</p>
              <p className="mt-1 text-xs leading-5 text-slate-400">Easy mode can refine size, but only to these board footprints.</p>
              <AllowedSizeGrid activeSize={widgetBrief.preferredSize} />
            </div>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
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
          </div>

          <div className="mt-4 flex flex-wrap gap-3">
            <ActionButton
              onClick={() => runGeneration("idea")}
              disabled={!idea.trim() || isPending || generationBlocked || !selectedProviderDetails?.supports_idea_to_spec}
              tone="primary"
            >
              {isPending ? "Generating..." : "Run Easy Generation"}
            </ActionButton>
            {currentJob ? (
              <ActionButton onClick={() => runGeneration("regenerate")} disabled={isPending || generationBlocked}>
                Regenerate Current
              </ActionButton>
            ) : null}
          </div>

          {providerUnavailable ? (
            <InlineNotice title="No providers available" body="Open System Panel to enable or configure at least one AI provider before generation." tone="warning" />
          ) : null}

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(340px,0.85fr)]">
            <GeneratedTestBox
              job={currentJob}
              packageArtifact={codeArtifact}
              testBox={currentTestBox}
              manifest={manifestArtifact}
              spec={specArtifact}
              sampleState={sampleState}
              widgetBrief={widgetBrief}
            />

            <div className="rounded-[18px] border border-white/10 bg-[#07090d] p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <p className="text-sm font-medium text-white">Feedback refinement</p>
                  <p className="mt-1 text-xs leading-5 text-slate-400">Feedback is routed as name, sizing, UI, or feature work, then returned as a new draft for testing.</p>
                </div>
              </div>
              <RefinementStatus
                activeCategory={normalizedFeedbackCategory}
                rawCategory={feedbackCategory}
                isRefining={isPending && Boolean(easyFeedback.trim())}
                lastFeedback={lastFeedback}
              />
              <textarea
                value={easyFeedback}
                onChange={(event) => {
                  const nextFeedback = event.target.value;
                  setEasyFeedback(nextFeedback);
                  setFeedbackCategory(nextFeedback.trim() ? inferFeedbackCategory(nextFeedback) : null);
                }}
                className="mt-3 min-h-[96px] w-full rounded-[14px] border border-white/10 bg-black/20 p-3 text-sm leading-6 text-slate-100 outline-none transition focus:border-cyan-300/30"
                placeholder="Example: make the status more compact, add stale data handling, or switch the preferred size to 2x2."
              />
              <div className="mt-3 flex justify-end">
                <ActionButton onClick={submitFeedback} disabled={!currentJob || !easyFeedback.trim() || isPending} tone="success">
                  {isPending ? "Submitting..." : "Submit Feedback"}
                </ActionButton>
              </div>
            </div>
          </div>
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
        <section className="space-y-5">
          <Panel
            eyebrow="Advanced"
            title="Provider and staged generation"
            description="Use the editor path when you want direct control over the staged spec before code generation."
          >
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-center">
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

function AllowedSizeGrid({ activeSize }: { activeSize: string | null }) {
  return (
    <div className="mt-3 grid grid-cols-3 gap-2">
      {allowedWidgetSizes.map((size) => (
        <span
          key={size}
          className={`rounded-[10px] border px-3 py-2 text-center text-xs font-medium ${
            activeSize === size
              ? "border-cyan-300/30 bg-cyan-300/12 text-cyan-50"
              : "border-white/10 bg-white/[0.04] text-slate-300"
          }`}
        >
          {size}
        </span>
      ))}
    </div>
  );
}

function RefinementStatus({
  activeCategory,
  rawCategory,
  isRefining,
  lastFeedback,
}: {
  activeCategory: FeedbackCategoryId | null;
  rawCategory: string | null;
  isRefining: boolean;
  lastFeedback: string | null;
}) {
  return (
    <div className="mt-4 space-y-3">
      <div className="grid gap-2 sm:grid-cols-2">
        {feedbackCategories.map((category) => {
          const active = category.id === activeCategory;
          return (
            <div
              key={category.id}
              className={`rounded-[14px] border px-3 py-3 ${
                active ? "border-cyan-300/24 bg-cyan-300/10" : "border-white/10 bg-black/20"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-white">{category.label}</p>
                <span className="rounded border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.12em] text-slate-300">
                  {active ? (isRefining ? "Refining" : "Routed") : "Waiting"}
                </span>
              </div>
              <p className="mt-1 text-xs leading-5 text-slate-400">{category.description}</p>
            </div>
          );
        })}
      </div>

      {rawCategory || lastFeedback ? (
        <div className="rounded-[14px] border border-white/10 bg-black/20 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Latest refinement</p>
          <p className="mt-1 text-sm text-slate-200">
            {rawCategory ? `Auto category: ${formatCategoryLabel(rawCategory)}` : "No category returned yet."}
          </p>
          {lastFeedback ? <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-400">{lastFeedback}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

function replaceJob(items: GenerationJob[], nextJob: GenerationJob) {
  const remaining = items.filter((item) => item.id !== nextJob.id);
  return [nextJob, ...remaining];
}

function GeneratedTestBox({
  job,
  packageArtifact,
  testBox,
  manifest,
  spec,
  sampleState,
  widgetBrief,
}: {
  job: GenerationJob | null;
  packageArtifact: GenerationArtifact | null;
  testBox: GenerationTestBox | null;
  manifest: JsonObject | null;
  spec: JsonObject | null;
  sampleState: JsonObject;
  widgetBrief: WidgetBrief;
}) {
  if (!job) {
    return <EmptyState title="No easy draft yet" body="Run easy generation to stage a package, manifest, spec, and sample state for inspection." />;
  }

  const stateEntries = Object.entries(sampleState).slice(0, 4);
  const packageFileCount = testBox?.files.length ?? packageArtifact?.files.length ?? 0;

  return (
    <div className="rounded-[18px] border border-white/10 bg-[#07090d] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Generated test box</p>
          <h3 className="mt-2 truncate text-lg font-semibold text-white">{widgetBrief.name}</h3>
          <p className="mt-1 text-sm leading-6 text-slate-400">{widgetBrief.description}</p>
        </div>
        <StatusBadge status={job.status} />
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-4">
        <div className="rounded-[14px] border border-white/10 bg-black/20 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Size</p>
          <p className="mt-1 text-sm font-medium text-white">{widgetBrief.preferredSize ?? "Unset"}</p>
        </div>
        <div className="rounded-[14px] border border-white/10 bg-black/20 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Category</p>
          <p className="mt-1 truncate text-sm font-medium text-white">{widgetBrief.category}</p>
        </div>
        <div className="rounded-[14px] border border-white/10 bg-black/20 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Package</p>
          <p className="mt-1 text-sm font-medium text-white">{packageFileCount} files</p>
        </div>
        <div className="rounded-[14px] border border-white/10 bg-black/20 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Version</p>
          <p className="mt-1 text-sm font-medium text-white">{job.selected_version}</p>
        </div>
      </div>

      <div className="mt-4 rounded-[16px] border border-white/10 bg-black/20 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-sm font-medium text-white">Agent spec summary</p>
            <p className="mt-1 text-xs leading-5 text-slate-400">Name, parameters, strict size, manifest, and renderer target inferred from the generated artifacts.</p>
          </div>
          <span
            className={`rounded-[10px] border px-3 py-1 text-xs uppercase tracking-[0.14em] ${
              widgetBrief.sizeAllowed
                ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-50"
                : "border-rose-300/20 bg-rose-300/10 text-rose-50"
            }`}
          >
            {widgetBrief.sizeAllowed ? "Grid valid" : "Invalid size"}
          </span>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {widgetBrief.parameters.length ? (
            widgetBrief.parameters.map((parameter) => (
              <div key={parameter.label} className="rounded-[12px] border border-white/10 bg-white/[0.03] px-3 py-2">
                <p className="text-[10px] uppercase tracking-[0.12em] text-slate-500">{parameter.label}</p>
                <p className="mt-1 truncate text-sm text-slate-100">{parameter.value}</p>
              </div>
            ))
          ) : (
            <p className="text-sm text-slate-400">No parameters were included with the generated draft.</p>
          )}
        </div>
      </div>

      <div className="mt-4 rounded-[16px] border border-cyan-300/14 bg-cyan-300/8 p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-medium text-white">Sample render state</p>
          <span className="rounded border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-slate-300">
            Test
          </span>
        </div>
        <div className="mt-3 grid gap-2">
          {stateEntries.length ? (
            stateEntries.map(([key, value]) => (
              <div key={key} className="flex items-center justify-between gap-3 rounded-[12px] border border-white/10 bg-black/20 px-3 py-2">
                <span className="truncate text-xs uppercase tracking-[0.12em] text-slate-500">{key}</span>
                <span className="truncate text-sm text-slate-100">{formatStateValue(value)}</span>
              </div>
            ))
          ) : (
            <p className="text-sm text-slate-400">No sample state was included with the generated artifact.</p>
          )}
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div>
          <p className="mb-2 text-xs uppercase tracking-[0.16em] text-slate-500">Manifest</p>
          <JsonBlock value={manifest ?? null} />
        </div>
        <div>
          <p className="mb-2 text-xs uppercase tracking-[0.16em] text-slate-500">Spec</p>
          <JsonBlock value={spec ?? null} />
        </div>
      </div>
    </div>
  );
}

interface WidgetBrief {
  name: string;
  description: string;
  category: string;
  preferredSize: string | null;
  sizeAllowed: boolean;
  parameters: Array<{ label: string; value: string }>;
}

function findArtifactPayload(job: GenerationJob | null, artifactNames: string[]) {
  if (!job) {
    return null;
  }

  for (const artifact of job.artifacts) {
    const nameMatches = artifactNames.some((name) => artifact.artifact_type.includes(name) || artifact.stage.includes(name));
    if (nameMatches && artifact.payload) {
      return artifact.payload;
    }

    const matchingFile = artifact.files.find((file) =>
      artifactNames.some((name) => file.path.toLowerCase().includes(name.toLowerCase()) && file.path.endsWith(".json")),
    );
    if (matchingFile) {
      try {
        const parsed = JSON.parse(matchingFile.content) as unknown;
        if (isJsonObject(parsed)) {
          return parsed;
        }
      } catch {
        return null;
      }
    }
  }

  return null;
}

function buildSampleState(job: GenerationJob | null, manifest: JsonObject | null, spec: JsonObject | null): JsonObject {
  const artifactState = findArtifactPayload(job, ["sample_state", "sample-state", "state"]);
  if (artifactState) {
    return artifactState;
  }

  const payloadState = [manifest?.sample_state, spec?.sample_state, spec?.state].find(isJsonObject);
  if (payloadState) {
    return payloadState;
  }

  return {
    title: typeof manifest?.name === "string" ? manifest.name : job?.widget_id ?? "Generated widget",
    status: job?.status ?? "draft",
    freshness: "sample",
    summary: typeof manifest?.description === "string" ? manifest.description : "Generated sample state",
  };
}

function buildWidgetBrief(
  job: GenerationJob | null,
  manifest: JsonObject | null,
  spec: JsonObject | null,
  testBox: GenerationTestBox | null,
): WidgetBrief {
  const preferredSize = pickString(testBox?.size, manifest?.preferred_size, spec?.preferred_size, spec?.size);
  const parameterSources = [
    testBox?.config_schema,
    manifest?.config_schema,
    manifest?.output_schema,
    spec?.parameters,
    spec?.config_schema,
    spec?.output_schema,
  ].filter(isJsonObject);
  const parameters = parameterSources.flatMap((source) => Object.entries(source).slice(0, 4)).slice(0, 6);

  return {
    name: pickString(testBox?.name, manifest?.name, spec?.name, job?.widget_id) ?? "Generated widget",
    description: pickString(testBox?.description, manifest?.description, spec?.description, job?.idea) ?? "Generated widget draft",
    category: pickString(testBox?.category, manifest?.category, spec?.category) ?? "custom",
    preferredSize,
    sizeAllowed: isAllowedWidgetSize(preferredSize),
    parameters: parameters.map(([label, value]) => ({
      label,
      value: formatStateValue(value),
    })),
  };
}

function isJsonObject(value: unknown): value is JsonObject {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function pickString(...values: unknown[]) {
  const found = values.find((value) => typeof value === "string" && value.trim().length > 0);
  return typeof found === "string" ? found : null;
}

function isAllowedWidgetSize(value: string | null): value is TileSize {
  return Boolean(value) && allowedWidgetSizes.includes(value as TileSize);
}

function normalizeFeedbackCategory(category: string | null): FeedbackCategoryId | null {
  if (!category) {
    return null;
  }

  const normalized = category.toLowerCase();
  if (normalized.includes("name") || normalized.includes("title") || normalized.includes("label")) {
    return "name";
  }
  if (normalized.includes("siz") || normalized.includes("grid") || normalized.includes("density")) {
    return "sizing";
  }
  if (normalized.includes("ui") || normalized.includes("visual") || normalized.includes("layout") || normalized.includes("renderer")) {
    return "ui";
  }
  return "feature";
}

function inferFeedbackCategory(feedback: string): FeedbackCategoryId {
  return normalizeFeedbackCategory(feedback) ?? "feature";
}

function formatCategoryLabel(category: string) {
  const normalized = normalizeFeedbackCategory(category);
  return feedbackCategories.find((item) => item.id === normalized)?.label ?? category;
}

function formatStateValue(value: unknown) {
  if (value === null || value === undefined) {
    return "null";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}
