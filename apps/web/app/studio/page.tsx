import Link from "next/link";
import type { Route } from "next";

import { SpecStudio } from "@/components/studio/spec-studio";

export default function StudioPage() {
  return (
    <main className="min-h-screen px-4 py-6 md:px-6 md:py-8">
      <div className="mx-auto max-w-6xl">
        <section className="glass-panel accent-border premium-ring rounded-[34px] p-6 md:p-7">
          <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <div className="max-w-3xl">
              <div className="flex flex-wrap items-center gap-3">
                <span className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-3 py-1 text-[11px] uppercase tracking-[0.28em] text-cyan-100">
                  Spec Studio
                </span>
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] uppercase tracking-[0.22em] text-slate-300">
                  Staged install path
                </span>
              </div>
              <h1 className="mt-4 text-4xl font-semibold tracking-tight text-white md:text-5xl">
                <span className="text-gradient">Widget Creation Pipeline</span>
              </h1>
              <p className="mt-3 text-sm leading-6 text-slate-300">
                Draft specs, validate manifests, inspect generated artifacts, review diffs, and install through the registry with a clear staged handoff.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Link
                href={"/system" as Route}
                className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-100 transition duration-200 hover:-translate-y-0.5 hover:bg-white/10"
              >
                System
              </Link>
              <Link
                href="/"
                className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-100 transition duration-200 hover:-translate-y-0.5 hover:bg-white/10"
              >
                Back to board
              </Link>
            </div>
          </div>

          <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              "1. Draft the spec",
              "2. Validate and scaffold",
              "3. Review generated output",
              "4. Install through registry",
            ].map((step) => (
              <div key={step} className="rounded-[24px] border border-white/10 bg-black/20 px-4 py-4 text-sm text-slate-200">
                {step}
              </div>
            ))}
          </div>
        </section>
      </div>
      <div className="mx-auto mt-8 max-w-6xl">
        <SpecStudio />
      </div>
    </main>
  );
}
