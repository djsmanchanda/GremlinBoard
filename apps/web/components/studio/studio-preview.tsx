"use client";

import { useMemo, useState } from "react";

import { BlueprintRenderer } from "@/components/board/blueprint-renderer";
import type { Blueprint } from "@/lib/blueprint";
import type {
  GenerationArtifactDiff,
  GenerationArtifactFile,
  JsonObject,
  SpecValidationResult,
  TileSize,
  WidgetInstance,
  WidgetManifest,
} from "@/lib/types";
import { EmptyState } from "@/components/studio/studio-ui";
import {
  previewFrameDimensions,
  previewSizes,
  type WidgetBrief,
} from "@/components/studio/studio-model";

type PreviewTab = "spec" | "manifest" | "backend" | "files";

const TAB_LABELS: Record<PreviewTab, string> = {
  spec: "Spec JSON",
  manifest: "Manifest",
  backend: "Backend code",
  files: "Files / diff",
};

export interface SpecEditorState {
  open: boolean;
  value: string;
  validation: SpecValidationResult | null;
  validating: boolean;
  onToggle: () => void;
  onChange: (value: string) => void;
}

export function StudioPreview({
  hasJob,
  generating,
  blueprint,
  sampleState,
  widgetBrief,
  manifest,
  spec,
  files,
  diffPreview,
  previewSize,
  onPreviewSize,
  specEditor,
}: {
  hasJob: boolean;
  generating: boolean;
  blueprint: Blueprint | null;
  sampleState: JsonObject;
  widgetBrief: WidgetBrief;
  manifest: JsonObject | null;
  spec: JsonObject | null;
  files: GenerationArtifactFile[];
  diffPreview: GenerationArtifactDiff[];
  previewSize: TileSize;
  onPreviewSize: (size: TileSize) => void;
  specEditor: SpecEditorState;
}) {
  const [activeTab, setActiveTab] = useState<PreviewTab>("spec");
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);

  const frame = previewFrameDimensions[previewSize];
  const previewWidget = useMemo<WidgetInstance>(
    () =>
      ({
        id: "studio-preview",
        widget_id: widgetBrief.name,
        size: previewSize,
        state: sampleState,
        blueprint: (blueprint as unknown as JsonObject) ?? null,
      }) as unknown as WidgetInstance,
    [blueprint, previewSize, sampleState, widgetBrief.name],
  );
  const previewManifest = (manifest ?? {}) as unknown as WidgetManifest;

  const backendFile = files.find((file) => file.path.toLowerCase().endsWith(".py")) ?? null;
  const selectedFile = files.find((file) => file.path === selectedFilePath) ?? files[0] ?? null;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Live preview</p>
            <p className="mt-1 text-sm text-slate-400">
              {blueprint
                ? "Rendered by the board's universal blueprint renderer with sample state."
                : "Blueprint unavailable — showing the draft summary."}
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Preview size">
            {previewSizes.map((size) => (
              <button
                key={size}
                type="button"
                aria-pressed={previewSize === size}
                onClick={() => onPreviewSize(size)}
                className={`rounded-control border px-2.5 py-1 text-xs font-medium transition ${
                  previewSize === size
                    ? "border-accent/40 bg-accent/12 text-accent"
                    : "border-edge bg-surface-inset text-slate-300 hover:border-accent/30 hover:text-accent"
                }`}
              >
                {size}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 flex min-h-[280px] items-center justify-center overflow-auto rounded-panel border border-edge bg-bg p-6">
          {blueprint ? (
            <div
              style={{ width: frame.width, height: frame.height }}
              className="max-w-full overflow-hidden rounded-panel border border-edge bg-surface p-3"
            >
              <BlueprintRenderer widget={previewWidget} manifest={previewManifest} />
            </div>
          ) : hasJob ? (
            <PreviewSummaryFallback widgetBrief={widgetBrief} generating={generating} />
          ) : (
            <EmptyState
              title="No preview yet"
              body="Describe a widget and generate to see it rendered live here."
              compact
            />
          )}
        </div>
      </div>

      <div>
        <div className="flex flex-wrap gap-1.5 border-b border-edge pb-3">
          {(Object.keys(TAB_LABELS) as PreviewTab[]).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={`rounded-control border px-3 py-1.5 text-xs transition ${
                activeTab === tab
                  ? "border-accent/30 bg-accent/10 text-accent"
                  : "border-edge bg-surface-inset text-slate-300 hover:bg-surface-raised"
              }`}
            >
              {TAB_LABELS[tab]}
            </button>
          ))}
        </div>

        <div className="pt-3">
          {activeTab === "spec" ? (
            <SpecTab specEditor={specEditor} spec={spec} />
          ) : activeTab === "manifest" ? (
            <JsonBlock value={manifest} emptyLabel="No manifest yet." />
          ) : activeTab === "backend" ? (
            backendFile ? (
              <CodeBlock content={backendFile.content} caption={backendFile.path} />
            ) : (
              <EmptyState title="No backend code" body="Backend code appears here after codegen finishes." compact />
            )
          ) : (
            <FilesTab
              files={files}
              diffPreview={diffPreview}
              selectedFile={selectedFile}
              onSelect={setSelectedFilePath}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function PreviewSummaryFallback({ widgetBrief, generating }: { widgetBrief: WidgetBrief; generating: boolean }) {
  return (
    <div className="w-full max-w-md rounded-panel border border-warn/30 bg-warn/8 p-4 text-left">
      <p className="text-[11px] uppercase tracking-[0.16em] text-warn/80">
        {generating ? "Rendering pending" : "Blueprint fallback"}
      </p>
      <p className="mt-2 text-lg font-semibold text-white">{widgetBrief.name}</p>
      <p className="mt-1 text-sm leading-6 text-slate-300">{widgetBrief.description}</p>
      <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-400">
        <span className="rounded-control border border-edge px-2 py-1">Category: {widgetBrief.category}</span>
        <span className="rounded-control border border-edge px-2 py-1">
          Size: {widgetBrief.preferredSize ?? "unset"}
        </span>
      </div>
      <p className="mt-3 text-xs leading-5 text-slate-500">
        {generating
          ? "Waiting for the generated blueprint. The live render appears as soon as codegen produces view.blueprint.json."
          : "This draft did not include a renderable blueprint; showing the draft metadata instead."}
      </p>
    </div>
  );
}

function SpecTab({ specEditor, spec }: { specEditor: SpecEditorState; spec: JsonObject | null }) {
  const validation = specEditor.validation;
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs uppercase tracking-[0.16em] text-slate-500">
          {specEditor.open ? "Editable spec (JSON)" : "Generated spec"}
        </p>
        <button
          type="button"
          onClick={specEditor.onToggle}
          className={`rounded-control border px-3 py-1 text-xs transition ${
            specEditor.open
              ? "border-accent/30 bg-accent/10 text-accent"
              : "border-edge bg-surface-inset text-slate-300 hover:bg-surface-raised"
          }`}
        >
          {specEditor.open ? "Done editing" : "Edit spec JSON"}
        </button>
      </div>

      {specEditor.open ? (
        <div className="space-y-2">
          <textarea
            value={specEditor.value}
            onChange={(event) => specEditor.onChange(event.target.value)}
            spellCheck={false}
            className={`min-h-[300px] w-full rounded-panel border bg-surface-inset p-4 font-mono text-xs leading-6 outline-none focus:border-accent/40 ${
              validation && !validation.valid ? "border-critical/40 text-critical" : "border-edge text-slate-100"
            }`}
          />
          <p className="text-xs text-slate-500">
            {specEditor.validating
              ? "Validating…"
              : validation
                ? validation.valid
                  ? `Valid · stage ${validation.stage_id}`
                  : validation.errors[0]?.message ?? "Spec has validation errors."
                : "Edit the spec, then use “Generate from edited spec” in the left panel."}
          </p>
        </div>
      ) : (
        <JsonBlock value={spec} emptyLabel="No spec yet." />
      )}
    </div>
  );
}

function FilesTab({
  files,
  diffPreview,
  selectedFile,
  onSelect,
}: {
  files: GenerationArtifactFile[];
  diffPreview: GenerationArtifactDiff[];
  selectedFile: GenerationArtifactFile | null;
  onSelect: (path: string) => void;
}) {
  if (files.length === 0) {
    return <EmptyState title="No generated files yet" body="Package contents appear here after codegen." compact />;
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {files.map((file) => (
          <button
            key={file.path}
            type="button"
            onClick={() => onSelect(file.path)}
            className={`rounded-control border px-2.5 py-1 text-xs transition ${
              file.path === selectedFile?.path
                ? "border-accent/30 bg-accent/10 text-accent"
                : "border-edge bg-surface-inset text-slate-300 hover:bg-surface-raised"
            }`}
          >
            {file.path.split("/").slice(-2).join("/")}
          </button>
        ))}
      </div>
      {selectedFile ? <CodeBlock content={selectedFile.content} caption={selectedFile.path} /> : null}
      {diffPreview.length > 0 ? (
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Diff summary</p>
          {diffPreview.map((item) => (
            <div key={item.path} className="rounded-panel border border-edge bg-surface-inset px-3 py-2">
              <p className="text-sm font-medium text-white">{item.path}</p>
              <p className="mt-1 text-xs text-slate-400">{item.summary}</p>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function JsonBlock({ value, emptyLabel }: { value: unknown; emptyLabel: string }) {
  if (value == null) {
    return <p className="text-sm text-slate-500">{emptyLabel}</p>;
  }
  return (
    <pre className="max-h-[420px] overflow-auto rounded-panel border border-edge bg-surface-inset p-4 text-xs leading-6 text-slate-200">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function CodeBlock({ content, caption }: { content: string; caption: string }) {
  return (
    <div className="space-y-1.5">
      <p className="font-mono text-[11px] text-slate-500">{caption}</p>
      <pre className="max-h-[420px] overflow-auto rounded-panel border border-edge bg-surface-inset p-4 text-xs leading-6 text-slate-200">
        {content}
      </pre>
    </div>
  );
}
