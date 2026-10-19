"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";

import { ApiError } from "@/src/shared/api";
import { instantiateTemplate } from "@/src/features/templates/api";
import {
  compileBodyFrom,
  compileReel,
  isJobFailed,
  pollCompileJob,
  type JobSnapshot,
} from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type ComposePhase =
  | "idle"
  | "compiling"
  | "polling"
  | "done"
  | "timeout"
  | "error";

export interface ComposeState {
  phase: ComposePhase;
  job?: JobSnapshot;
  error?: string;
}

export interface RunArgs {
  slug: string;
  inputs: Record<string, unknown>;
  durationS?: number;
}

const INITIAL: ComposeState = { phase: "idle" };

/**
 * Drives the template → render-job pipeline: instantiate the template, POST the
 * pipeline-ready reel draft to `/jobs`, then poll `/jobs/{id}` to a terminal state. All
 * transitions are surfaced as an immutable {@link ComposeState} so the UI can
 * render distinct compiling / polling / done / timeout / error states. The in-
 * flight request is aborted on unmount or when a new run starts.
 */
export function useCompile() {
  const { getToken } = useAuth();
  const [state, setState] = React.useState<ComposeState>(INITIAL);
  const abortRef = React.useRef<AbortController | null>(null);

  React.useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const reset = React.useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setState(INITIAL);
  }, []);

  const run = React.useCallback(
    async ({ slug, inputs, durationS }: RunArgs) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const { signal } = controller;

      setState({ phase: "compiling" });
      try {
        const token = (await getToken()) ?? undefined;
        const instantiation = await instantiateTemplate(
          slug,
          { inputs, duration_s: durationS },
          { token, signal },
        );
        const { job_id } = await compileReel(compileBodyFrom(instantiation), {
          token,
          signal,
        });

        setState({ phase: "polling", job: { job_id } });
        const result = await pollCompileJob(job_id, {
          token,
          signal,
          onTick: (job) =>
            setState((prev) => ({ ...prev, phase: "polling", job })),
        });

        if (signal.aborted) return;
        if (result.timedOut) {
          setState({ phase: "timeout", job: result.value });
        } else if (isJobFailed(result.value)) {
          setState({
            phase: "error",
            job: result.value,
            error:
              result.value.error ||
              "Rendering failed. Please review your inputs and try again.",
          });
        } else {
          setState({ phase: "done", job: result.value });
        }
      } catch (err) {
        if (signal.aborted || (err instanceof DOMException && err.name === "AbortError")) {
          return;
        }
        setState({
          phase: "error",
          error:
            friendlyErrorMessage(err, "Something went wrong compiling your reel."),
        });
      }
    },
    [getToken],
  );

  return { state, run, reset } as const;
}
