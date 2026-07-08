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
  const visibleHeadlines = headlines.slice(0, compact ? 1 : tier === "expanded" ? 6 : 3);

  return (
    <div className="flex h-full flex-col gap-2">
      {!compact ? (
        <div className="flex items-center justify-between gap-3">
          <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Headlines</p>
          <span className="text-[10px] uppercase tracking-[0.12em] text-slate-400">{topic}</span>
        </div>
      ) : null}

      {visibleHeadlines.length === 0 ? (
        <p className="p-3 text-xs text-slate-400">Awaiting headlines.</p>
      ) : (
        <div className="divide-y divide-edge">
          {visibleHeadlines.map((item, index) => (
            <article key={`${item.title}-${index}`} className="py-2.5 first:pt-0">
              <p className={`font-medium text-slate-100 ${compact ? "line-clamp-3 text-xs leading-5" : "line-clamp-2 text-sm leading-5"}`}>
                {item.title}
              </p>
              {!compact ? <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-400">{item.summary}</p> : null}
              <p className="mt-2 text-[10px] uppercase tracking-[0.14em] text-slate-500">
                {item.source} / {item.published_at}
              </p>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

