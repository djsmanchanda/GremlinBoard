import type { WidgetRendererProps } from "@/lib/types";

export function CountdownRenderer({ widget }: WidgetRendererProps) {
  const label = typeof widget.state.label === "string" ? widget.state.label : widget.title;
  const remaining = typeof widget.state.formatted_remaining === "string" ? widget.state.formatted_remaining : "--:--:--";
  const targetTime = typeof widget.state.target_time === "string" ? widget.state.target_time : "";
  return (
    <div className="flex h-full flex-col justify-between">
      <div>
        <p className="text-xs uppercase tracking-[0.24em] text-slate-400">Countdown</p>
        <h3 className="mt-2 text-lg font-semibold text-white">{label}</h3>
      </div>
      <div className="rounded-2xl border border-cyan-400/20 bg-cyan-400/10 p-3">
        <p className="font-mono text-3xl font-semibold tracking-[0.2em] text-cyan-100">{remaining}</p>
        <p className="mt-2 text-xs text-slate-300">Target {targetTime ? new Date(targetTime).toLocaleString() : "-"}</p>
      </div>
    </div>
  );
}
