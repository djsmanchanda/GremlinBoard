"use client";

import { useEffect } from "react";

import { fetchEasyGenerationJob, fetchGenerationJob } from "@/lib/api";
import { apiWebSocketUrl } from "@/lib/constants";
import type { GenerationJob, GenerationTestBox, RuntimeEventMessage } from "@/lib/types";
import { isGenerating } from "@/components/studio/studio-model";

/**
 * Streaming transport for an in-flight generation job (P4.2). While a job is
 * generating, `/board/stream` websocket generation events are the primary
 * signal; each matching event triggers exactly one authoritative REST fetch
 * (the event payload is partial and never drives UI state directly). The 1.2s
 * REST poll is retained only as a fallback while the socket is disconnected.
 * Callers pass stable callbacks (via useCallback) so the effect does not
 * re-arm on every render; the effect re-arms only when the active job id, the
 * easy/regular transport choice, or the generating flag changes.
 */

export const GENERATION_POLL_INTERVAL_MS = 1200;

const RECONNECT_BASE_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 30000;

interface GenerationEventPayload {
  job_id?: string;
  stage?: string;
  progress?: number;
}

interface UseGenerationJobParams {
  job: GenerationJob | null;
  /** Job id that should be fetched through the easy-generation (test-box) endpoint. */
  easyJobId: string | null;
  onJob: (job: GenerationJob) => void;
  onTestBox: (testBox: GenerationTestBox | null) => void;
}

export function useGenerationJob({ job, easyJobId, onJob, onTestBox }: UseGenerationJobParams): void {
  const jobId = job && isGenerating(job) ? job.id : null;
  const useEasyEndpoint = jobId !== null && easyJobId === jobId;

  useEffect(() => {
    if (!jobId) {
      return;
    }

    let closed = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let reconnectAttempt = 0;
    let pollTimer: number | null = null;
    let fetchInFlight = false;
    let refetchQueued = false;

    // Every trigger (event, reconnect resync, fallback poll tick) funnels
    // through here; overlapping triggers coalesce into one queued refetch.
    const refresh = () => {
      if (closed) {
        return;
      }
      if (fetchInFlight) {
        refetchQueued = true;
        return;
      }
      fetchInFlight = true;
      const request = useEasyEndpoint
        ? fetchEasyGenerationJob(jobId).then((response) => {
            if (closed) {
              return;
            }
            onJob(response.job);
            onTestBox(response.test_box ?? null);
          })
        : fetchGenerationJob(jobId).then((next) => {
            if (closed) {
              return;
            }
            onJob(next);
          });
      void request
        .catch(() => undefined)
        .finally(() => {
          fetchInFlight = false;
          if (refetchQueued && !closed) {
            refetchQueued = false;
            refresh();
          }
        });
    };

    const stopPolling = () => {
      if (pollTimer !== null) {
        window.clearTimeout(pollTimer);
        pollTimer = null;
      }
    };

    const startPolling = () => {
      if (closed || pollTimer !== null) {
        return;
      }
      pollTimer = window.setTimeout(() => {
        pollTimer = null;
        refresh();
        startPolling();
      }, GENERATION_POLL_INTERVAL_MS);
    };

    const clearReconnect = () => {
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const closeSocket = () => {
      clearReconnect();
      const activeSocket = socket;
      socket = null;
      activeSocket?.close();
    };

    const scheduleReconnect = () => {
      if (closed || document.visibilityState !== "visible" || reconnectTimer !== null) {
        return;
      }
      const delay = Math.min(RECONNECT_MAX_DELAY_MS, RECONNECT_BASE_DELAY_MS * 2 ** reconnectAttempt);
      reconnectAttempt += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    };

    const connect = () => {
      if (closed || socket || document.visibilityState === "hidden") {
        return;
      }
      const nextSocket = new WebSocket(apiWebSocketUrl("/board/stream"));
      socket = nextSocket;
      nextSocket.onopen = () => {
        if (socket !== nextSocket) {
          return;
        }
        reconnectAttempt = 0;
        stopPolling();
        // Single resync per (re)connect: events emitted while disconnected
        // would otherwise be lost until the next one arrives.
        refresh();
      };
      nextSocket.onmessage = (event) => {
        if (socket !== nextSocket) {
          return;
        }
        let message: RuntimeEventMessage<GenerationEventPayload>;
        try {
          message = JSON.parse(event.data as string) as RuntimeEventMessage<GenerationEventPayload>;
        } catch {
          return;
        }
        if (message.category !== "generation" || message.payload?.job_id !== jobId) {
          return;
        }
        refresh();
      };
      nextSocket.onerror = () => {
        // Socket failures fall back to polling; never surfaced as Studio errors.
      };
      nextSocket.onclose = () => {
        if (socket !== nextSocket) {
          return;
        }
        socket = null;
        if (closed) {
          return;
        }
        startPolling();
        scheduleReconnect();
      };
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        closeSocket();
        startPolling();
        return;
      }
      reconnectAttempt = 0;
      connect();
    };

    // Poll until the socket reports open; onopen clears the timer.
    startPolling();
    connect();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      closed = true;
      stopPolling();
      closeSocket();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [jobId, useEasyEndpoint, onJob, onTestBox]);
}
