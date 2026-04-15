import { getWidgetDisplayTier } from "@/lib/widget-display";
import type { WidgetRendererProps } from "@/lib/types";

export function NewsRenderer({ widget }: WidgetRendererProps) {
  const headlines = Array.isArray(widget.state.headlines)
    ? (widget.state.headlines as Array<{
        title: string;
        summary: string;
        source: string;
        published_at: string;
      }>)
    : [];
  const topic = typeof widget.state.topic === "string" ? widget.state.topic : "general";
  const tier = getWidgetDisplayTier(widget.size);
  const compact = tier === "compact";
  const visibleHeadlines = headlines.slice(0, compact ? 1 : tier === "expanded" ? 4 : 2);

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">News</p>
          <h3 className={`mt-1 truncate font-semibold text-white ${compact ? "text-sm" : "text-base"}`}>{widget.title}</h3>
        </div>
        {!compact ? <span className="rounded border border-white/10 bg-white/5 px-2 py-1 text-[10px] uppercase tracking-[0.12em] text-slate-300">{topic}</span> : null}
      </div>

      <div className="grid gap-2">
        {visibleHeadlines.length === 0 ? (
          <div className="rounded-[14px] border border-dashed border-white/12 bg-white/[0.03] p-3 text-xs text-slate-400">
            Waiting for headlines.
          </div>
        ) : (
          visibleHeadlines.map((item, index) => (
            <article key={`${item.title}-${index}`} className="rounded-[14px] border border-white/10 bg-white/[0.04] p-3">
              <p className={`font-medium text-slate-100 ${compact ? "line-clamp-3 text-xs leading-5" : "line-clamp-2 text-sm leading-5"}`}>
                {item.title}
              </p>
              {!compact ? <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-400">{item.summary}</p> : null}
              <p className="mt-2 text-[10px] uppercase tracking-[0.14em] text-slate-500">
                {item.source} · {item.published_at}
              </p>
            </article>
          ))
        )}
      </div>
    </div>
  );
}
