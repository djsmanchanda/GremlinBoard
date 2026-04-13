import type { WidgetPreset } from "@/lib/types";

export const WIDGET_PRESETS: WidgetPreset[] = [
  {
    key: "countdown-default",
    label: "Countdown Timer",
    widget_id: "countdown",
    title: "Countdown Timer",
    size: "1x2",
    config: {
      label: "Next release",
      target_time: new Date(Date.now() + 1000 * 60 * 90).toISOString(),
    },
  },
  {
    key: "sports-ipl",
    label: "IPL Live",
    widget_id: "sports",
    title: "IPL Live",
    size: "4x2",
    config: { sport: "ipl" },
  },
  {
    key: "sports-f1",
    label: "F1 Session",
    widget_id: "sports",
    title: "F1 Session",
    size: "4x2",
    config: { sport: "f1" },
  },
  {
    key: "sports-football",
    label: "Football Watch",
    widget_id: "sports",
    title: "Football Watch",
    size: "4x2",
    config: { sport: "football" },
  },
  {
    key: "news-default",
    label: "News Radar",
    widget_id: "news",
    title: "News Radar",
    size: "2x2",
    config: { topic: "openclaw", sources: ["demo"] },
  },
  {
    key: "trending-default",
    label: "Trend Stack",
    widget_id: "trending",
    title: "Trend Stack",
    size: "2x4",
    config: { sources: ["reddit", "x", "hackernews"] },
  },
  {
    key: "pinboard-default",
    label: "Personal Pinboard",
    widget_id: "pinboard",
    title: "Personal Pinboard",
    size: "2x4",
    config: {
      notes: [
        { id: "1", text: "Drop in a new note and it persists in the widget config." },
      ],
    },
  },
];
