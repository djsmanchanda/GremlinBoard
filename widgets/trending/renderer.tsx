import type { WidgetRendererProps } from "@/lib/types";

export function TrendingRenderer({ widget }: WidgetRendererProps) {
  const sections = Array.isArray(widget.state.sections)
    ? (widget.state.sections as Array<{
        source: string;
        items?: Array<{ label: string; score: number }>;
      }>)
    : [];
  return (
    <div className="flex h-full flex-col">
      <div className="mb-4">
        <p className="text-xs uppercase tracking-[0.24em] text-fuchsia-300/70">Trending</p>
        <h3 className="mt-1 text-lg font-semibold text-white">{widget.title}</h3>
      </div>
      <div className="grid gap-3">
        {sections.map((section) => (
          <section key={section.source} className="rounded-2xl border border-white/10 bg-white/5 p-3">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-400">{section.source}</p>
            </div>
            <div className="space-y-2">
              {(section.items ?? []).slice(0, 3).map((item, index) => (
                <div key={`${item.label}-${index}`} className="flex items-center justify-between gap-3">
                  <p className="text-sm text-slate-100">{item.label}</p>
                  <span className="text-xs text-slate-400">{item.score}</span>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
