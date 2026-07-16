"use client";

import { useCallback, useEffect, useMemo, useState, useTransition } from "react";

import {
  approveGenerationJob,
  createEasyGenerationJob,
  createGenerationJob,
  fetchAIProviders,
  fetchGenerationJobs,
  installGenerationJob,
  previewSpecDocument,
  rejectGenerationJob,
  submitGenerationFeedback,
} from "@/lib/api";
import type {
  GenerationJob,
  GenerationTestBox,
  SpecValidationResult,
  TileSize,
} from "@/lib/types";
import { StudioConversation, type ThreadEntry } from "@/components/studio/studio-conversation";
import { StudioPreview, type SpecEditorState } from "@/components/studio/studio-preview";
import { StatusBadge } from "@/components/studio/studio-ui";
import { useGenerationJob as useGenerationJobEffect } from "@/components/studio/use-generation-job";
import {
  getDefaultModelId,
  getDefaultReasoningEffort,
  getProviderModelOptions,
} from "@/components/studio/provider-utils";
import {
  buildIdeaWithSelectedSize,
  buildSampleState,
  buildWidgetBrief,
  defaultWidgetSize,
  extractBlueprint,
  isAllowedWidgetSize,
  isGenerating,
  replaceJob,
  selectCodeArtifact,
  selectManifest,
  selectSpec,
} from "@/components/studio/studio-model";

const defaultSpecDraft = JSON.stringify(
  {
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
  },
  null,
  2,
);

export function SpecStudio() {
  // Provider selection
  const [providers, setProviders] = useState<Awaited<ReturnType<typeof fetchAIProviders>>>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>("codex");
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [selectedReasoningEffort, setSelectedReasoningEffort] = useState<string>("");

  // Idea + size
  const [idea, setIdea] = useState(
    "Build a compact operations status widget with refresh health, active alerts, and a short summary.",
  );
  const [selectedSize, setSelectedSize] = useState<TileSize>(defaultWidgetSize);

  // Job + refinement state
  const [currentJob, setCurrentJob] = useState<GenerationJob | null>(null);
  const [currentTestBox, setCurrentTestBox] = useState<GenerationTestBox | null>(null);
  const [easyJobId, setEasyJobId] = useState<string | null>(null);
  const [jobHistory, setJobHistory] = useState<GenerationJob[]>([]);
  const [thread, setThread] = useState<Array<Omit<ThreadEntry, "status" | "summary">>>([]);
  const [feedback, setFeedback] = useState("");
  const [reviewNote, setReviewNote] = useState("");

  // Preview + spec editor
  const [previewSize, setPreviewSize] = useState<TileSize>(defaultWidgetSize);
  const [specEditorOpen, setSpecEditorOpen] = useState(false);
  const [specDraft, setSpecDraft] = useState(defaultSpecDraft);
  const [specValidation, setSpecValidation] = useState<SpecValidationResult | null>(null);
  const [specValidating, setSpecValidating] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  // ---- Load providers + history once ----
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
        // Prefer a provider with a working AI backend (api key or agent CLI)
        // over one that would silently fall back to offline templates.
        const usable = (provider: (typeof providerItems)[number]) =>
          provider.backend != null && provider.backend !== "offline";
        const activeProvider =
          [
            providerItems.find((provider) => provider.provider_id === selectedProvider && usable(provider)),
            providerItems.find(usable),
            providerItems.find((provider) => provider.provider_id === selectedProvider),
            providerItems[0],
          ].find(Boolean) ?? null;
        if (activeProvider) {
          setSelectedProvider(activeProvider.provider_id);
          const defaultModelId = getDefaultModelId(activeProvider);
          setSelectedModel(defaultModelId);
          setSelectedReasoningEffort(getDefaultReasoningEffort(activeProvider, defaultModelId));
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
    // Mount-only load; provider changes are handled by the change handler.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- Polling transport (extracted hook) ----
  const onJob = useCallback((job: GenerationJob) => {
    setCurrentJob(job);
    setJobHistory((items) => replaceJob(items, job));
  }, []);
  const onTestBox = useCallback((testBox: GenerationTestBox | null) => {
    setCurrentTestBox(testBox);
  }, []);
  useGenerationJobEffect({ job: currentJob, easyJobId, onJob, onTestBox });

  // ---- Derived provider values ----
  const selectedProviderDetails = providers.find((provider) => provider.provider_id === selectedProvider) ?? null;
  const modelOptions = useMemo(
    () => (selectedProviderDetails ? getProviderModelOptions(selectedProviderDetails) : []),
    [selectedProviderDetails],
  );
  const selectedModelDetails = useMemo(
    () => modelOptions.find((model) => model.id === selectedModel) ?? modelOptions[0] ?? null,
    [modelOptions, selectedModel],
  );
  const reasoningEffortOptions = useMemo(
    () => selectedModelDetails?.reasoning_effort_options ?? [],
    [selectedModelDetails],
  );
  const fallbackProviders = providers
    .filter((provider) => provider.provider_id !== selectedProvider)
    .map((provider) => provider.provider_id);

  useEffect(() => {
    if (reasoningEffortOptions.length === 0) {
      if (selectedReasoningEffort) {
        setSelectedReasoningEffort("");
      }
      return;
    }
    if (!reasoningEffortOptions.includes(selectedReasoningEffort)) {
      setSelectedReasoningEffort(reasoningEffortOptions.includes("medium") ? "medium" : reasoningEffortOptions[0]);
    }
  }, [reasoningEffortOptions, selectedReasoningEffort]);

  // ---- Derived job artifacts ----
  const codeArtifact = useMemo(() => selectCodeArtifact(currentJob), [currentJob]);
  const manifestArtifact = useMemo(() => selectManifest(currentJob, currentTestBox), [currentJob, currentTestBox]);
  const specArtifact = useMemo(() => selectSpec(currentJob), [currentJob]);
  const sampleState = useMemo(
    () => buildSampleState(currentJob, currentTestBox, manifestArtifact, specArtifact),
    [currentJob, currentTestBox, manifestArtifact, specArtifact],
  );
  const widgetBrief = useMemo(
    () => buildWidgetBrief(currentJob, currentTestBox, manifestArtifact, specArtifact),
    [currentJob, currentTestBox, manifestArtifact, specArtifact],
  );
  const blueprint = useMemo(
    () => extractBlueprint(currentJob, currentTestBox, manifestArtifact),
    [currentJob, currentTestBox, manifestArtifact],
  );
  const files = useMemo(
    () => currentTestBox?.files ?? codeArtifact?.files ?? [],
    [codeArtifact, currentTestBox],
  );

  const generationSettled = Boolean(currentJob && !isGenerating(currentJob));
  const generatedGridIssue = Boolean(
    generationSettled && (!widgetBrief.preferredSize || !widgetBrief.sizeAllowed),
  );

  // Sync preview tier to the generated size when a fresh test box arrives.
  useEffect(() => {
    if (currentTestBox && isAllowedWidgetSize(currentTestBox.size)) {
      setPreviewSize(currentTestBox.size);
    }
  }, [currentTestBox]);

  // ---- Spec editor validation (debounced) ----
  useEffect(() => {
    if (!specEditorOpen) {
      return;
    }
    setSpecValidating(true);
    const timeout = window.setTimeout(() => {
      void previewSpecDocument({ format: "json", content: specDraft })
        .then((response) => setSpecValidation(response))
        .catch((validationError) =>
          setError(validationError instanceof Error ? validationError.message : "Spec validation failed"),
        )
        .finally(() => setSpecValidating(false));
    }, 450);
    return () => window.clearTimeout(timeout);
  }, [specEditorOpen, specDraft]);

  // ---- Provider change ----
  const handleProviderChange = (providerId: string) => {
    const provider = providers.find((item) => item.provider_id === providerId);
    const defaultModelId = provider ? getDefaultModelId(provider) : "";
    setSelectedProvider(providerId);
    setSelectedModel(defaultModelId);
    setSelectedReasoningEffort(provider ? getDefaultReasoningEffort(provider, defaultModelId) : "");
  };

  const providerUnavailable = providers.length === 0;
  const generationBlocked = providerUnavailable || !selectedProviderDetails;

  const baseRequest = () => ({
    provider_id: selectedProvider,
    model_id: selectedModel || undefined,
    reasoning_effort: selectedReasoningEffort || undefined,
    fallback_provider_ids: fallbackProviders,
  });

  // ---- Generation actions ----
  const runEasyGeneration = () => {
    setError(null);
    const trimmed = idea.trim();
    startTransition(() => {
      void createEasyGenerationJob({ ...baseRequest(), idea: buildIdeaWithSelectedSize(trimmed, selectedSize) })
        .then((response) => {
          setCurrentJob(response.job);
          setCurrentTestBox(response.test_box ?? null);
          setEasyJobId(response.job.id);
          setJobHistory((items) => replaceJob(items, response.job));
          setThread([{ id: response.job.id, kind: "idea", text: trimmed, category: null }]);
          setFeedback("");
        })
        .catch((requestError) => {
          setError(requestError instanceof Error ? requestError.message : "Generation failed");
        });
    });
  };

  const runRegenerate = () => {
    if (!currentJob) {
      return;
    }
    setError(null);
    startTransition(() => {
      void createGenerationJob({ ...baseRequest(), regenerate_from_job_id: currentJob.id })
        .then((job) => {
          setCurrentJob(job);
          setCurrentTestBox(null);
          setEasyJobId(job.id);
          setJobHistory((items) => replaceJob(items, job));
        })
        .catch((requestError) => {
          setError(requestError instanceof Error ? requestError.message : "Regeneration failed");
        });
    });
  };

  const runGenerateFromSpec = () => {
    if (!specValidation?.valid || !specValidation.stage_id) {
      return;
    }
    setError(null);
    startTransition(() => {
      void createGenerationJob({ ...baseRequest(), stage_id: specValidation.stage_id })
        .then((job) => {
          setCurrentJob(job);
          setCurrentTestBox(null);
          setEasyJobId(null);
          setJobHistory((items) => replaceJob(items, job));
          setThread([{ id: job.id, kind: "idea", text: "Generated from edited spec JSON.", category: "spec" }]);
        })
        .catch((requestError) => {
          setError(requestError instanceof Error ? requestError.message : "Generation failed");
        });
    });
  };

  const submitFeedback = () => {
    if (!currentJob || !feedback.trim()) {
      return;
    }
    const trimmed = feedback.trim();
    setError(null);
    startTransition(() => {
      void submitGenerationFeedback(currentJob.id, { ...baseRequest(), feedback: trimmed })
        .then((response) => {
          setCurrentJob(response.job);
          setCurrentTestBox(response.test_box ?? null);
          setEasyJobId(response.job.id);
          setJobHistory((items) => replaceJob(items, response.job));
          setThread((items) => [
            ...items,
            { id: `${response.job.id}-${items.length}`, kind: "feedback", text: trimmed, category: response.category },
          ]);
          setFeedback("");
        })
        .catch((requestError) => {
          setError(requestError instanceof Error ? requestError.message : "Refinement failed");
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

  // ---- Gating reasons ----
  const gridSizeMessage = "Set a strict preferred size (1x1, 1x2, 2x2, 4x2, 2x4, 4x4)";

  const generateReasons: string[] = [];
  if (generationBlocked) {
    generateReasons.push("No AI provider is available");
  }
  if (!idea.trim()) {
    generateReasons.push("Enter a widget idea");
  }
  if (selectedProviderDetails && !selectedProviderDetails.supports_idea_to_spec) {
    generateReasons.push(`Provider ${selectedProviderDetails.label} cannot generate from an idea`);
  }

  const generateFromSpecReasons: string[] = [];
  if (generationBlocked) {
    generateFromSpecReasons.push("No AI provider is available");
  }
  if (specValidating) {
    generateFromSpecReasons.push("Validating spec…");
  } else if (!specValidation) {
    generateFromSpecReasons.push("Edit the spec to validate it first");
  } else if (!specValidation.valid) {
    generateFromSpecReasons.push(specValidation.errors[0]?.message ?? "Fix spec validation errors");
  }

  // Backend state machine: completed --approve--> review_required --install--> installed.
  // approve_job accepts only "completed"; install_job accepts "review_required"/"approved";
  // reject_job accepts "completed"/"review_required".
  const approveReasons: string[] = [];
  const installReasons: string[] = [];
  if (currentJob) {
    if (currentJob.status === "review_required" || currentJob.status === "approved") {
      approveReasons.push("Already approved — ready to install");
    } else if (currentJob.status !== "completed") {
      approveReasons.push(`Generation must finish first (status: ${currentJob.status})`);
    }
    if (generatedGridIssue) {
      approveReasons.push(gridSizeMessage);
    }
    if (!["review_required", "approved"].includes(currentJob.status)) {
      installReasons.push(`Approve the job first (status: ${currentJob.status})`);
    }
    if (generatedGridIssue) {
      installReasons.push(gridSizeMessage);
    }
    if (currentJob.install_blocked && currentJob.status !== "completed") {
      installReasons.push("Install blocked by pipeline checks");
    }
    if (currentJob.error_message) {
      approveReasons.push(currentJob.error_message);
      installReasons.push(currentJob.error_message);
    }
  }
  const rejectDisabled =
    isPending || !currentJob || !["completed", "review_required"].includes(currentJob.status);

  // ---- Thread with live status ----
  const renderedThread: ThreadEntry[] = thread.map((entry, index) => {
    const isLast = index === thread.length - 1;
    const status: GenerationJob["status"] = isLast && currentJob ? currentJob.status : "completed";
    const summary = isLast
      ? isGenerating(currentJob)
        ? "Generating draft…"
        : `${widgetBrief.name} · ${widgetBrief.preferredSize ?? "size unset"}`
      : "Superseded by a newer draft";
    return { ...entry, status, summary };
  });

  // ---- Progress line ----
  const generating = isGenerating(currentJob);
  const progressLabel = generating
    ? currentJob?.current_step
      ? currentJob.current_step
      : "Generating widget"
    : null;
  const progressPercent = generating ? currentJob?.progress ?? null : null;

  // ---- Spec editor wiring ----
  const specEditor: SpecEditorState = {
    open: specEditorOpen,
    value: specDraft,
    validation: specValidation,
    validating: specValidating,
    onToggle: () => {
      setSpecEditorOpen((open) => {
        const next = !open;
        if (next && specArtifact) {
          setSpecDraft(JSON.stringify(specArtifact, null, 2));
        }
        return next;
      });
    },
    onChange: setSpecDraft,
  };

  return (
    <div className="space-y-5">
      {error ? (
        <div className="rounded-panel border border-critical/30 bg-critical/8 px-4 py-3 text-sm text-critical">
          <p className="text-[10px] uppercase tracking-[0.18em] text-critical/80">Studio warning</p>
          <p className="mt-1">{error}</p>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <section className="rounded-panel border border-edge bg-surface p-5">
          <StudioConversation
            idea={idea}
            onIdeaChange={setIdea}
            selectedSize={selectedSize}
            onSelectSize={setSelectedSize}
            providers={providers}
            selectedProvider={selectedProvider}
            modelOptions={modelOptions}
            selectedModel={selectedModel}
            reasoningEffortOptions={reasoningEffortOptions}
            selectedReasoningEffort={selectedReasoningEffort}
            onProviderChange={handleProviderChange}
            onModelChange={setSelectedModel}
            onReasoningEffortChange={setSelectedReasoningEffort}
            providerUnavailable={providerUnavailable}
            isPending={isPending}
            progressLabel={progressLabel}
            progressPercent={progressPercent}
            onGenerate={runEasyGeneration}
            generateReasons={generateReasons}
            hasJob={Boolean(currentJob)}
            onRegenerate={runRegenerate}
            regenerateDisabled={isPending || generationBlocked}
            specEditorOpen={specEditorOpen}
            onGenerateFromSpec={runGenerateFromSpec}
            generateFromSpecReasons={generateFromSpecReasons}
            thread={renderedThread}
            feedback={feedback}
            onFeedbackChange={setFeedback}
            onSubmitFeedback={submitFeedback}
            feedbackDisabled={!currentJob || !feedback.trim() || isPending}
            job={currentJob}
            onApprove={() => runReviewAction("approve")}
            onReject={() => runReviewAction("reject")}
            onInstall={() => runReviewAction("install")}
            approveReasons={approveReasons}
            installReasons={installReasons}
            rejectDisabled={rejectDisabled}
            reviewNote={reviewNote}
            onReviewNoteChange={setReviewNote}
          />
        </section>

        <section className="rounded-panel border border-edge bg-surface p-5">
          <StudioPreview
            hasJob={Boolean(currentJob)}
            generating={generating}
            blueprint={blueprint}
            sampleState={sampleState}
            widgetBrief={widgetBrief}
            manifest={manifestArtifact}
            spec={specArtifact}
            files={files}
            diffPreview={currentJob?.diff_preview ?? []}
            previewSize={previewSize}
            onPreviewSize={setPreviewSize}
            specEditor={specEditor}
          />
        </section>
      </div>

      <HistoryFooter jobs={jobHistory} currentJobId={currentJob?.id ?? null} onSelect={setCurrentJob} />
    </div>
  );
}


function HistoryFooter({
  jobs,
  currentJobId,
  onSelect,
}: {
  jobs: GenerationJob[];
  currentJobId: string | null;
  onSelect: (job: GenerationJob) => void;
}) {
  if (jobs.length === 0) {
    return null;
  }
  return (
    <details className="rounded-panel border border-edge bg-surface">
      <summary className="cursor-pointer list-none px-5 py-3 text-[11px] uppercase tracking-[0.2em] text-slate-500">
        Recent jobs ({jobs.length})
      </summary>
      <div className="grid gap-2 border-t border-edge px-5 py-4 sm:grid-cols-2 xl:grid-cols-3">
        {jobs.map((job) => (
          <button
            key={job.id}
            type="button"
            onClick={() => onSelect(job)}
            className={`flex items-center justify-between gap-3 rounded-control border px-3 py-2 text-left transition ${
              currentJobId === job.id
                ? "border-accent/30 bg-accent/8"
                : "border-edge bg-surface-inset hover:bg-surface-raised"
            }`}
          >
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-white">{job.widget_id}</span>
              <span className="mt-0.5 block truncate text-xs text-slate-400">
                {job.provider_id} · v{job.artifact_version}
              </span>
            </span>
            <StatusBadge status={job.status} />
          </button>
        ))}
      </div>
    </details>
  );
}
