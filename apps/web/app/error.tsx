"use client";

import Link from "next/link";
import type { Route } from "next";
import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("GremlinBoard route error", error);
  }, [error]);

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-8">
      <div className="w-full max-w-2xl rounded-[32px] border border-rose-400/20 bg-rose-400/10 p-6">
        <p className="text-xs uppercase tracking-[0.24em] text-rose-200/80">Route Error</p>
        <h1 className="mt-3 text-3xl font-semibold text-white">This page failed to load.</h1>
        <p className="mt-3 text-sm text-rose-50/90">
          {error.message || "GremlinBoard could not recover the current route state."}
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => reset()}
            className="rounded-full border border-white/10 bg-white/10 px-4 py-2 text-sm text-white transition hover:bg-white/15"
          >
            Retry page
          </button>
          <Link
            href="/"
            className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/10"
          >
            Board
          </Link>
          <Link
            href={"/system" as Route}
            className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/10"
          >
            System panel
          </Link>
        </div>
      </div>
    </main>
  );
}
