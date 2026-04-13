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
      <div className="rounded-2xl border border-dashed border-white/10 p-4 text-sm text-slate-400">
        No renderer registered for {props.manifest.renderer.target}.
      </div>
    );
  }

  return <Component {...props} />;
}
