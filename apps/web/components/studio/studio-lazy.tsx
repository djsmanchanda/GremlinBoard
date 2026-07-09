"use client";

import dynamic from "next/dynamic";

// Client-only lazy boundary: `ssr: false` dynamic imports must live in a Client
// Component. This keeps the studio bundle out of the initial server render so the
// board route stays light.
const SpecStudio = dynamic(() => import("@/components/studio/spec-studio").then((mod) => mod.SpecStudio), {
  ssr: false,
  loading: () => <p className="text-sm text-slate-400">Loading Spec Studio…</p>,
});

export function StudioLazy() {
  return <SpecStudio />;
}
