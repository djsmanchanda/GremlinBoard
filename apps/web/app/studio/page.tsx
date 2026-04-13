import Link from "next/link";

import { SpecStudio } from "@/components/studio/spec-studio";

export default function StudioPage() {
  return (
    <main className="min-h-screen px-4 py-6 md:px-6">
      <div className="mx-auto flex max-w-6xl items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-slate-400">Spec Studio</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">Widget Creation Pipeline</h1>
        </div>
        <Link
          href="/"
          className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/10"
        >
          Back to board
        </Link>
      </div>
      <div className="mx-auto mt-8 max-w-6xl">
        <SpecStudio />
      </div>
    </main>
  );
}
