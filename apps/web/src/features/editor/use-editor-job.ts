"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { ApiError, getJob, POLL_INTERVAL_MS } from "@/lib/api";
import { isTerminalState, type Job } from "@/lib/types";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type EditorJobState =
  | { status: "idle"; job: null; error: "" }
  | { status: "loading"; job: null; error: "" }
  | { status: "ready"; job: Job; error: "" }
  | { status: "error"; job: Job | null; error: string };

function messageOf(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return friendlyErrorMessage(error);
  return "Could not load this Menivor job.";
}

export function useEditorJob(jobId: string): EditorJobState {
  const { getToken, isLoaded } = useAuth();
  const [state, setState] = React.useState<EditorJobState>(() =>
    jobId ? { status: "loading", job: null, error: "" } : { status: "idle", job: null, error: "" },
  );

  React.useEffect(() => {
    if (!jobId) {
      setState({ status: "idle", job: null, error: "" });
      return;
    }
    if (!isLoaded) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    const poll = async (): Promise<void> => {
      try {
        const token = (await getToken()) ?? undefined;
        const job = await getJob(jobId, { token, signal: controller.signal });
        if (cancelled) return;
        setState({ status: "ready", job, error: "" });
        if (!isTerminalState(job.state)) {
          timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
        }
      } catch (error) {
        if (cancelled || (error instanceof DOMException && error.name === "AbortError")) return;
        setState((previous) => ({
          status: "error",
          job: previous.job,
          error: messageOf(error),
        }));
      }
    };

    setState({ status: "loading", job: null, error: "" });
    void poll();
    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [getToken, isLoaded, jobId]);

  return state;
}
