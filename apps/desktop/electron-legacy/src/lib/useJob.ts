/**
 * Job polling for the ReelForge Desktop renderer.
 *
 * The desktop client does not run the render pipeline — it creates a job and
 * polls GET /jobs/{id} every few seconds until the job reaches a terminal state
 * (Complete or Failed), per §5 of the integration contract. This module exposes
 * both the imperative primitive (`pollJob`) used by the wizard and a small React
 * hook (`useJob`) that drives a live status view and cleans up on unmount.
 */

import { useEffect, useRef, useState } from "react";

import { getJob } from "./api";
import type { Job } from "./types";
import { isFailedState, isTerminalState } from "./types";

/** How often GET /jobs/{id} is polled, per the contract (every 3s). */
export const POLL_INTERVAL_MS = 3000;

/** Default hard cap on total poll attempts before giving up (~20 min at 3s). */
export const DEFAULT_MAX_POLL_ATTEMPTS = 400;

export interface PollOptions {
  /** Poll cadence in ms (default {@link POLL_INTERVAL_MS}). */
  intervalMs?: number;
  /** Hard cap on total attempts before timing out (default 400 ≈ 20 min). */
  maxAttempts?: number;
  /** Abort signal to stop polling. */
  signal?: AbortSignal;
}

/**
 * Polls GET /jobs/{id} until the job reaches a terminal state, invoking
 * `onTick(job)` on every successful poll. Resolves with the final terminal Job.
 * Rejects with an `AbortError` if `signal` fires, or a plain Error on timeout.
 */
export async function pollJob(
  id: string,
  onTick: (job: Job) => void,
  options?: PollOptions,
): Promise<Job> {
  const intervalMs = options?.intervalMs ?? POLL_INTERVAL_MS;
  const maxAttempts = options?.maxAttempts ?? DEFAULT_MAX_POLL_ATTEMPTS;
  const signal = options?.signal;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (signal?.aborted) throw new DOMException("Polling aborted", "AbortError");

    const job = await getJob(id);
    onTick(job);
    if (isTerminalState(job.state)) return job;

    await delay(intervalMs, signal);
  }

  throw new Error(`Timed out waiting for job ${id} to complete.`);
}

/** Resolves after `ms`, or rejects immediately if `signal` aborts. */
function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/** Reactive state returned by {@link useJob}. */
export interface UseJobResult {
  /** The latest job snapshot, or null before the first successful poll. */
  job: Job | null;
  /** True while actively polling a non-terminal job. */
  polling: boolean;
  /** Backend/network error message, or null. */
  error: string | null;
  /** True once the job has reached a terminal state (Complete or Failed). */
  isTerminal: boolean;
  /** True when the job ended in the failed state. */
  isFailed: boolean;
}

const IDLE: UseJobResult = {
  job: null,
  polling: false,
  error: null,
  isTerminal: false,
  isFailed: false,
};

/**
 * React hook that polls a job to completion. Pass a `jobId` (or null/undefined to
 * stay idle); the hook polls GET /jobs/{id} every {@link POLL_INTERVAL_MS} until
 * the job is terminal, exposing a live `{ job, polling, error, isTerminal,
 * isFailed }`. Polling is aborted automatically on unmount or when `jobId`
 * changes, so no request outlives the component.
 */
export function useJob(
  jobId: string | null | undefined,
  options?: Pick<PollOptions, "intervalMs" | "maxAttempts">,
): UseJobResult {
  const [state, setState] = useState<UseJobResult>(IDLE);
  const intervalMs = options?.intervalMs;
  const maxAttempts = options?.maxAttempts;

  // Guards against a stale async loop writing state after unmount / id change.
  const activeRef = useRef(true);

  useEffect(() => {
    if (!jobId) {
      setState(IDLE);
      return;
    }

    activeRef.current = true;
    const controller = new AbortController();
    setState({ ...IDLE, polling: true });

    pollJob(
      jobId,
      (job) => {
        if (!activeRef.current) return;
        setState({
          job,
          polling: !isTerminalState(job.state),
          error: null,
          isTerminal: isTerminalState(job.state),
          isFailed: isFailedState(job.state),
        });
      },
      { intervalMs, maxAttempts, signal: controller.signal },
    ).catch((err: unknown) => {
      if (!activeRef.current) return;
      // A deliberate abort (unmount / id change) is not a user-facing error.
      if (err instanceof DOMException && err.name === "AbortError") return;
      setState((prev) => ({
        ...prev,
        polling: false,
        error: err instanceof Error ? err.message : String(err),
      }));
    });

    return () => {
      activeRef.current = false;
      controller.abort();
    };
  }, [jobId, intervalMs, maxAttempts]);

  return state;
}
