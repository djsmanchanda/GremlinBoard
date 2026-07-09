"use client";

import { useEffect } from "react";

import { fetchEasyGenerationJob, fetchGenerationJob } from "@/lib/api";
import type { GenerationJob, GenerationTestBox } from "@/lib/types";
import { isGenerating } from "@/components/studio/studio-model";

/**
 * Polling transport for an in-flight generation job (P4.1). The 1.2s poll is
 * intentionally isolated here so a follow-up packet (P4.2) can swap it for the
 * websocket / SSE stream without touching the studio UI. Callers pass stable
 * callbacks (via useCallback) so the effect does not re-arm on every render.
 */

export const GENERATION_POLL_INTERVAL_MS = 1200;

interface UseGenerationJobParams {
  job: GenerationJob | null;
  /** Job id that should be polled through the easy-generation (test-box) endpoint. */
  easyJobId: string | null;
  onJob: (job: GenerationJob) => void;
  onTestBox: (testBox: GenerationTestBox | null) => void;
}

export function useGenerationJob({ job, easyJobId, onJob, onTestBox }: UseGenerationJobParams): void {
  useEffect(() => {
    if (!isGenerating(job) || !job) {
      return;
    }
    const timeout = window.setTimeout(() => {
      if (easyJobId === job.id) {
        void fetchEasyGenerationJob(job.id)
          .then((response) => {
            onJob(response.job);
            onTestBox(response.test_box ?? null);
          })
          .catch(() => undefined);
        return;
      }
      void fetchGenerationJob(job.id)
        .then((next) => onJob(next))
        .catch(() => undefined);
    }, GENERATION_POLL_INTERVAL_MS);
    return () => window.clearTimeout(timeout);
  }, [job, easyJobId, onJob, onTestBox]);
}
