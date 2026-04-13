"use client";

import Link from "next/link";
import type { Route } from "next";
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  message: string | null;
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("GremlinBoard client boundary caught an error", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="flex min-h-screen items-center justify-center px-4 py-8">
          <div className="w-full max-w-2xl rounded-[32px] border border-rose-400/20 bg-rose-400/10 p-6">
            <p className="text-xs uppercase tracking-[0.24em] text-rose-200/80">Recovery</p>
            <h1 className="mt-3 text-3xl font-semibold text-white">The interface hit a client error.</h1>
            <p className="mt-3 text-sm text-rose-50/90">
              {this.state.message ?? "A rendering failure interrupted the current view."}
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => this.setState({ hasError: false, message: null })}
                className="rounded-full border border-white/10 bg-white/10 px-4 py-2 text-sm text-white transition hover:bg-white/15"
              >
                Retry render
              </button>
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="rounded-full border border-rose-200/30 bg-rose-200/15 px-4 py-2 text-sm text-rose-50 transition hover:bg-rose-200/20"
              >
                Reload app
              </button>
              <Link
                href={"/system" as Route}
                className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/10"
              >
                Open system panel
              </Link>
            </div>
          </div>
        </main>
      );
    }
    return this.props.children;
  }
}
