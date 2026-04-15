import { getWidgetDisplayTier } from "@/lib/widget-display";
import type { WidgetRendererProps } from "@/lib/types";

export function TrendingRenderer({ widget }: WidgetRendererProps) {
  const sections = Array.isArray(widget.state.sections)
    ? (widget.state.sections as Array<{
        source: string;
        items?: Array<{ label: string; score: number }>;
      }>)
    : [];
  const tier = getWidgetDisplayTier(widget.size);
  const compact = tier === "compact";
  const visibleSections = sections.slice(0, compact ? 1 : tier === "expanded" ? 4 : 2);

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="min-w-0">
        <p className="text-[10px] uppercase tracking-[0.18em] text-fuchsia-300/70">Trending</p>
        <h3 className={`mt-1 truncate font-semibold text-white ${compact ? "text-sm" : "text-base"}`}>{widget.title}</h3>
      </div>

      <div className="grid gap-2">
        {visibleSections.map((section) => (
          <section key={section.source} className="rounded-[14px] border border-white/10 bg-white/[0.04] p-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-[10px] uppercase tracking-[0.14em] text-slate-400">{section.source}</p>
            </div>
            <div className="mt-2 space-y-2">
              {(section.items ?? []).slice(0, compact ? 2 : 3).map((item, index) => (
                <div key={`${item.label}-${index}`} className="flex items-start justify-between gap-3">
                  <p className={`text-slate-100 ${compact ? "line-clamp-2 text-xs leading-5" : "text-sm leading-5"}`}>{item.label}</p>
                  <span className="shrink-0 text-[11px] text-slate-400">{item.score}</span>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
