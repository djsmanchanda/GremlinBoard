import Link from "next/link";
import type { Route } from "next";

import { StudioLazy } from "@/components/studio/studio-lazy";

export default function StudioPage() {
  return (
    <main className="min-h-screen px-4 py-6 md:px-6 md:py-8">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div className="max-w-3xl">
            <h1 className="text-3xl font-semibold tracking-tight text-white md:text-4xl">Spec Studio</h1>
            <p className="mt-2 text-sm leading-6 text-slate-400">
              Describe a widget, watch it render live, refine by conversation, then review and install — one guided flow.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={"/system" as Route}
              className="rounded-control border border-edge bg-surface-inset px-4 py-2 text-sm text-slate-100 transition hover:bg-surface-raised"
            >
              System
            </Link>
            <Link
              href="/"
              className="rounded-control border border-edge bg-surface-inset px-4 py-2 text-sm text-slate-100 transition hover:bg-surface-raised"
            >
              Back to board
            </Link>
          </div>
        </div>
      </div>
      <div className="mx-auto mt-6 max-w-6xl">
        <StudioLazy />
      </div>
    </main>
  );
}
