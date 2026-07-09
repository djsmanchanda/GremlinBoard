"use client";

import type { ReactNode } from "react";

import type { GenerationJob } from "@/lib/types";

export function ActionButton({
  children,
  onClick,
  disabled,
  tone = "default",
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  tone?: "default" | "primary" | "success" | "danger";
  type?: "button" | "submit";
}) {
  const toneClass =
    tone === "primary"
      ? "border-accent/30 bg-accent/10 text-accent hover:bg-accent/16"
      : tone === "success"
        ? "border-ok/30 bg-ok/10 text-ok hover:bg-ok/16"
        : tone === "danger"
          ? "border-critical/30 bg-critical/10 text-critical hover:bg-critical/16"
          : "border-edge bg-surface-inset text-slate-100 hover:bg-surface-raised";

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-control border px-4 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-50 ${toneClass}`}
    >
      {children}
    </button>
  );
}

export function StatusBadge({ status }: { status: GenerationJob["status"] }) {
  const styles =
    status === "installed"
      ? "border-ok/30 bg-ok/10 text-ok"
      : status === "approved"
        ? "border-accent/30 bg-accent/10 text-accent"
        : status === "review_required"
          ? "border-warn/30 bg-warn/10 text-warn"
          : status === "failed" || status === "rejected"
            ? "border-critical/30 bg-critical/10 text-critical"
            : "border-edge bg-surface-inset text-slate-200";
  return (
    <span className={`rounded-control border px-3 py-1 text-xs uppercase tracking-[0.14em] ${styles}`}>{status}</span>
  );
}

export function InlineNotice({
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
      className={`rounded-panel border px-4 py-3 ${
        tone === "warning" ? "border-warn/30 bg-warn/8 text-warn" : "border-edge bg-surface-inset text-slate-200"
      }`}
    >
      <p className="text-sm font-medium">{title}</p>
      <p className={`mt-1 text-sm leading-6 ${tone === "warning" ? "text-warn/80" : "text-slate-400"}`}>{body}</p>
    </div>
  );
}

export function EmptyState({ title, body, compact = false }: { title: string; body: string; compact?: boolean }) {
  return (
    <div className={`rounded-panel border border-dashed border-edge bg-surface-inset text-center ${compact ? "p-4" : "p-5"}`}>
      <p className="text-sm font-medium text-white">{title}</p>
      <p className="mt-2 text-sm leading-6 text-slate-400">{body}</p>
    </div>
  );
}

/** A muted "why is this disabled" reason list rendered next to a gated button. */
export function GatingReasons({ reasons }: { reasons: string[] }) {
  if (reasons.length === 0) {
    return null;
  }
  return (
    <ul className="mt-1 space-y-1 text-xs leading-5 text-warn/80">
      {reasons.map((reason) => (
        <li key={reason} className="flex gap-1.5">
          <span aria-hidden className="text-warn/60">
            •
          </span>
          <span>{reason}</span>
        </li>
      ))}
    </ul>
  );
}
