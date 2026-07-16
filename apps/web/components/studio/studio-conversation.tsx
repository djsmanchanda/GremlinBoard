"use client";

import type { AIModelOption, AIProvider, GenerationJob, TileSize } from "@/lib/types";
import { ProviderControl } from "@/components/studio/provider-control";
import { ActionButton, GatingReasons, InlineNotice, StatusBadge } from "@/components/studio/studio-ui";
import { allowedWidgetSizes, selectTokenUsageLabel } from "@/components/studio/studio-model";

export interface ThreadEntry {
  id: string;
  kind: "idea" | "feedback";
  text: string;
  category?: string | null;
  status: GenerationJob["status"];
  summary: string;
}

export interface ConversationProps {
  idea: string;
  onIdeaChange: (value: string) => void;
  selectedSize: TileSize;
  onSelectSize: (size: TileSize) => void;

  providers: AIProvider[];
  selectedProvider: string;
  modelOptions: AIModelOption[];
  selectedModel: string;
  reasoningEffortOptions: string[];
  selectedReasoningEffort: string;
  onProviderChange: (providerId: string) => void;
  onModelChange: (modelId: string) => void;
  onReasoningEffortChange: (effort: string) => void;
  providerUnavailable: boolean;

  isPending: boolean;
  progressLabel: string | null;
  progressPercent: number | null;

  onGenerate: () => void;
  generateReasons: string[];
  hasJob: boolean;
  onRegenerate: () => void;
  regenerateDisabled: boolean;

  specEditorOpen: boolean;
  onGenerateFromSpec: () => void;
  generateFromSpecReasons: string[];

  thread: ThreadEntry[];
  feedback: string;
  onFeedbackChange: (value: string) => void;
  onSubmitFeedback: () => void;
  feedbackDisabled: boolean;

  job: GenerationJob | null;
  onApprove: () => void;
  onReject: () => void;
  onInstall: () => void;
  approveReasons: string[];
  installReasons: string[];
  rejectDisabled: boolean;
  reviewNote: string;
  onReviewNoteChange: (value: string) => void;
}

export function StudioConversation(props: ConversationProps) {
  const generateBlocked = props.generateReasons.length > 0;

  return (
    <div className="flex flex-col gap-6">
      {/* Idea + strict size */}
      <div>
        <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Describe the widget</p>
        <textarea
          value={props.idea}
          onChange={(event) => props.onIdeaChange(event.target.value)}
          className="mt-2 min-h-[120px] w-full rounded-panel border border-edge bg-surface-inset p-4 text-sm leading-6 text-slate-100 outline-none focus:border-accent/40"
          placeholder="Describe the widget idea, expected data source, and board behavior."
        />
        <div className="mt-3 flex flex-wrap items-center gap-2" role="group" aria-label="Strict size">
          <span className="text-[11px] uppercase tracking-[0.16em] text-slate-500">Strict size</span>
          {allowedWidgetSizes.map((size) => (
            <button
              key={size}
              type="button"
              aria-pressed={props.selectedSize === size}
              onClick={() => props.onSelectSize(size)}
              className={`rounded-control border px-2.5 py-1 text-xs font-medium transition ${
                props.selectedSize === size
                  ? "border-accent/40 bg-accent/12 text-accent"
                  : "border-edge bg-surface-inset text-slate-300 hover:border-accent/30 hover:text-accent"
              }`}
            >
              {size}
            </button>
          ))}
        </div>
      </div>

      {/* One provider control */}
      <ProviderControl
        providers={props.providers}
        selectedProvider={props.selectedProvider}
        modelOptions={props.modelOptions}
        selectedModel={props.selectedModel}
        reasoningEffortOptions={props.reasoningEffortOptions}
        selectedReasoningEffort={props.selectedReasoningEffort}
        onProviderChange={props.onProviderChange}
        onModelChange={props.onModelChange}
        onReasoningEffortChange={props.onReasoningEffortChange}
      />

      {props.providerUnavailable ? (
        <InlineNotice
          title="No providers available"
          body="Open System Panel to enable or configure at least one AI provider before generation."
          tone="warning"
        />
      ) : null}

      {/* Generate actions */}
      <div>
        <div className="flex flex-wrap gap-2">
          <ActionButton onClick={props.onGenerate} disabled={props.isPending || generateBlocked} tone="primary">
            {props.isPending ? "Generating…" : "Generate"}
          </ActionButton>
          {props.hasJob ? (
            <ActionButton onClick={props.onRegenerate} disabled={props.regenerateDisabled}>
              Regenerate
            </ActionButton>
          ) : null}
          {props.specEditorOpen ? (
            <ActionButton
              onClick={props.onGenerateFromSpec}
              disabled={props.isPending || props.generateFromSpecReasons.length > 0}
              tone="success"
            >
              Generate from edited spec
            </ActionButton>
          ) : null}
        </div>
        <GatingReasons reasons={generateBlocked ? props.generateReasons : []} />
        {props.specEditorOpen ? <GatingReasons reasons={props.generateFromSpecReasons} /> : null}
      </div>

      {/* Inline progress line */}
      {props.progressLabel ? (
        <div>
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>{props.progressLabel}</span>
            {props.progressPercent != null ? <span>{props.progressPercent}%</span> : null}
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-inset">
            <div
              className="h-full rounded-full bg-accent transition-all"
              style={{ width: `${props.progressPercent ?? 15}%` }}
            />
          </div>
        </div>
      ) : null}

      {/* Refinement thread */}
      {props.thread.length > 0 ? (
        <div className="space-y-3">
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Refinement</p>
          {props.thread.map((entry) => (
            <div key={entry.id} className="rounded-panel border border-edge bg-surface-inset p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] uppercase tracking-[0.14em] text-slate-500">
                  {entry.kind === "idea" ? "Idea" : `Feedback${entry.category ? ` · ${entry.category}` : ""}`}
                </span>
                <StatusBadge status={entry.status} />
              </div>
              <p className="mt-2 text-sm text-slate-100">{entry.text}</p>
              <p className="mt-1 text-xs leading-5 text-slate-400">{entry.summary}</p>
            </div>
          ))}
        </div>
      ) : null}

      {props.hasJob ? (
        <div>
          <label className="text-[11px] uppercase tracking-[0.16em] text-slate-500" htmlFor="studio-feedback">
            Refine by conversation
          </label>
          <textarea
            id="studio-feedback"
            value={props.feedback}
            onChange={(event) => props.onFeedbackChange(event.target.value)}
            className="mt-2 min-h-[80px] w-full rounded-panel border border-edge bg-surface-inset p-3 text-sm leading-6 text-slate-100 outline-none focus:border-accent/40"
            placeholder="Example: make the status more compact, add stale-data handling, or switch to a table layout."
          />
          <div className="mt-2 flex justify-end">
            <ActionButton onClick={props.onSubmitFeedback} disabled={props.feedbackDisabled} tone="success">
              {props.isPending ? "Submitting…" : "Send refinement"}
            </ActionButton>
          </div>
        </div>
      ) : null}

      {/* Review verdict */}
      {props.job ? (
        <ReviewSection {...props} />
      ) : null}
    </div>
  );
}

function ReviewSection(props: ConversationProps) {
  const job = props.job;
  if (!job) {
    return null;
  }
  const target = job.install_target;
  const tokenUsageLabel = selectTokenUsageLabel(job);
  return (
    <div className="border-t border-edge pt-5">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Review</p>
          <p className="mt-1 truncate text-sm font-medium text-white">{job.widget_id}</p>
        </div>
        <StatusBadge status={job.status} />
      </div>

      <p className="mt-2 text-xs text-slate-400">
        {target?.action === "update" ? "Update installed widget" : "Install new widget"} to{" "}
        {target?.next_version ?? job.selected_version}
        {target?.current_version ? ` (current ${target.current_version})` : ""}
      </p>
      {tokenUsageLabel ? <p className="mt-1 text-xs text-slate-400">{tokenUsageLabel}</p> : null}
      {job.generation_mode === "cli" ? (
        <p className="mt-1 text-xs text-slate-400">
          Generated through the local {job.provider_id === "claude" ? "Claude Code" : "Codex"} CLI
        </p>
      ) : null}

      {job.generation_mode === "offline" ? (
        <div className="mt-3">
          <InlineNotice
            tone="warning"
            title="Generated in offline template mode — no AI was used"
            body={`The ${job.provider_id === "claude" ? "Claude" : "Codex"} provider found neither a logged-in agent CLI nor an API key, so this widget came from the deterministic template fallback. Either install and log in to the ${job.provider_id === "claude" ? "Claude Code CLI (claude)" : "Codex CLI (codex)"} — no API key needed — or add a credential in the System panel (provider "${job.provider_id === "claude" ? "anthropic" : "openai"}"), then Regenerate.`}
          />
        </div>
      ) : null}

      <div className="mt-4 space-y-3">
        <div>
          <ActionButton
            onClick={props.onApprove}
            disabled={props.isPending || props.approveReasons.length > 0}
            tone="success"
          >
            Approve
          </ActionButton>
          <GatingReasons reasons={props.approveReasons} />
        </div>
        <div className="flex flex-wrap gap-2">
          <ActionButton onClick={props.onReject} disabled={props.rejectDisabled} tone="danger">
            Reject
          </ActionButton>
          <div className="flex-1">
            <ActionButton
              onClick={props.onInstall}
              disabled={props.isPending || props.installReasons.length > 0}
              tone="primary"
            >
              Install
            </ActionButton>
            <GatingReasons reasons={props.installReasons} />
          </div>
        </div>
      </div>

      <textarea
        value={props.reviewNote}
        onChange={(event) => props.onReviewNoteChange(event.target.value)}
        className="mt-4 min-h-[70px] w-full rounded-panel border border-edge bg-surface-inset p-3 text-sm text-slate-100 outline-none focus:border-accent/40"
        placeholder="Optional review note or rejection reason."
      />
    </div>
  );
}
