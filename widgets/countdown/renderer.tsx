import { getWidgetDisplayTier } from "@/lib/widget-display";
import type { WidgetRendererProps } from "@/lib/types";

export function CountdownRenderer({ widget }: WidgetRendererProps) {
  const label = typeof widget.state.label === "string" ? widget.state.label : widget.title;
  const remaining = typeof widget.state.formatted_remaining === "string" ? widget.state.formatted_remaining : "--:--:--";
  const targetTime = typeof widget.state.target_time === "string" ? widget.state.target_time : "";
  const tier = getWidgetDisplayTier(widget.size);
  const compact = tier === "compact";

  return (
    <div className="flex h-full flex-col justify-between gap-3">
      <div className="min-w-0">
        <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Countdown</p>
        <h3 className={`mt-1 truncate font-semibold text-white ${compact ? "text-sm" : "text-base"}`}>{label}</h3>
      </div>

      <div className={`rounded-[14px] border border-cyan-400/18 bg-cyan-400/10 ${compact ? "p-2.5" : "p-3"}`}>
        <p
          className={`font-mono font-semibold tracking-[0.16em] text-cyan-100 ${
            compact ? "text-lg leading-6" : tier === "expanded" ? "text-4xl leading-none" : "text-3xl leading-none"
          }`}
        >
          {remaining}
        </p>
        {!compact ? (
          <p className="mt-2 text-xs text-slate-300">Target {targetTime ? new Date(targetTime).toLocaleString() : "-"}</p>
        ) : null}
      </div>
    </div>
  );
}
