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
  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-slate-400">News</p>
          <h3 className="mt-1 text-lg font-semibold text-white">{widget.title}</h3>
        </div>
        <span className="rounded-full bg-slate-900 px-3 py-1 text-xs text-slate-300">{topic}</span>
      </div>
      <div className="space-y-3">
        {headlines.slice(0, 3).map((item, index) => (
          <article key={`${item.title}-${index}`} className="rounded-2xl border border-white/10 bg-white/5 p-3">
            <p className="text-sm font-medium text-slate-100">{item.title}</p>
            <p className="mt-1 text-xs text-slate-400">{item.summary}</p>
            <p className="mt-2 text-[11px] uppercase tracking-[0.18em] text-slate-500">
              {item.source} · {item.published_at}
            </p>
          </article>
        ))}
      </div>
    </div>
  );
}
