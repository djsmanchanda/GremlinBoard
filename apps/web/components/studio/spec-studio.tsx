"use client";

import { useState } from "react";

import { validateSpec } from "@/lib/api";

interface SpecValidationResult {
  stage_id: string;
  stage: string;
  valid: boolean;
  notes: string[];
  scaffold_preview: {
    files: string[];
  };
}

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

export function SpecStudio() {
  const [payload, setPayload] = useState(JSON.stringify(defaultSpec, null, 2));
  const [result, setResult] = useState<SpecValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleValidate() {
    setError(null);
    try {
      const parsed = JSON.parse(payload) as Record<string, unknown>;
      const response = (await validateSpec(parsed)) as SpecValidationResult;
      setResult(response);
    } catch (validateError) {
      setError(validateError instanceof Error ? validateError.message : "Validation failed");
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
      <section className="rounded-[28px] border border-white/10 bg-white/5 p-5">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Draft</p>
        <h2 className="mt-2 text-xl font-semibold text-white">Spec-first widget input</h2>
        <p className="mt-2 text-sm text-slate-300">
          This stage only validates and previews scaffold artifacts. It does not install or execute generated code.
        </p>
        <textarea
          value={payload}
          onChange={(event) => setPayload(event.target.value)}
          className="mt-4 min-h-[420px] w-full rounded-3xl border border-white/10 bg-slate-950/80 p-4 font-mono text-sm text-slate-100 outline-none focus:border-cyan-300/40"
        />
        <button
          type="button"
          onClick={handleValidate}
          className="mt-4 rounded-full border border-cyan-300/20 bg-cyan-300/10 px-4 py-2 text-sm text-cyan-100 transition hover:bg-cyan-300/20"
        >
          Validate spec
        </button>
        {error ? <p className="mt-3 text-sm text-rose-300">{error}</p> : null}
      </section>
      <section className="rounded-[28px] border border-white/10 bg-white/5 p-5">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Pipeline</p>
        <h2 className="mt-2 text-xl font-semibold text-white">Validation result</h2>
        {!result ? (
          <p className="mt-4 text-sm text-slate-300">Run validation to stage the draft and preview scaffold output.</p>
        ) : (
          <div className="mt-4 space-y-4">
            <div className="rounded-2xl border border-white/10 bg-slate-950/70 p-4">
              <p className="text-sm text-slate-200">Stage: {result.stage}</p>
              <p className="mt-1 text-sm text-slate-200">Valid: {String(result.valid)}</p>
              <p className="mt-1 text-xs text-slate-400">Stage id: {result.stage_id}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-slate-950/70 p-4">
              <p className="text-sm font-medium text-white">Notes</p>
              <ul className="mt-2 space-y-2 text-sm text-slate-300">
                {result.notes.length === 0 ? (
                  <li>No blocking issues detected.</li>
                ) : (
                  result.notes.map((note: string) => <li key={note}>{note}</li>)
                )}
              </ul>
            </div>
            <div className="rounded-2xl border border-white/10 bg-slate-950/70 p-4">
              <p className="text-sm font-medium text-white">Scaffold preview</p>
              <ul className="mt-2 space-y-2 text-sm text-slate-300">
                {result.scaffold_preview.files.map((file: string) => (
                  <li key={file}>{file}</li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
