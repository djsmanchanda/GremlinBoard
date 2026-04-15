import { CountdownRenderer } from "@widgets/countdown/renderer";
import { NewsRenderer } from "@widgets/news/renderer";
import { PinboardRenderer } from "@widgets/pinboard/renderer";
import { SportsRenderer } from "@widgets/sports/renderer";
import { TrendingRenderer } from "@widgets/trending/renderer";

import type { WidgetRendererProps } from "@/lib/types";

const registry = {
  countdown: CountdownRenderer,
  news: NewsRenderer,
  sports: SportsRenderer,
  trending: TrendingRenderer,
  pinboard: PinboardRenderer,
} as const;

export function WidgetRenderer(props: WidgetRendererProps) {
  const Component = registry[props.manifest.renderer.target as keyof typeof registry];
  if (!Component) {
    return (
      <div className="flex h-full min-h-[180px] items-center justify-center rounded-[22px] border border-dashed border-amber-300/20 bg-amber-300/8 p-5 text-center">
        <div>
          <p className="text-[11px] uppercase tracking-[0.2em] text-amber-100/75">Renderer missing</p>
          <p className="mt-3 text-sm font-medium text-white">No renderer registered for `{props.manifest.renderer.target}`.</p>
          <p className="mt-2 text-sm leading-6 text-slate-300">
            The widget manifest loaded, but the UI plugin surface for this target is unavailable in the current build.
          </p>
        </div>
      </div>
    );
  }

  return <Component {...props} />;
}
