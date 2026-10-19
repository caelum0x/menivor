"use client";

import * as React from "react";
import { ApiError, suggestBroll } from "@/lib/api";
import type { BrollClip, SuggestBrollParams } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type BrollStatus = "idle" | "loading" | "ready" | "error";

export interface UseBrollSuggestionsResult {
  clips: readonly BrollClip[];
  status: BrollStatus;
  error: string;
  /** Trigger a fresh suggestion (button-driven; aborts any in-flight call). */
  suggest: (params?: SuggestBrollParams) => void;
}

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * On-demand loader for AI B-roll suggestions (POST /jobs/{id}/broll/suggest).
 * Unlike the catalog hooks this never auto-fetches — the creator explicitly asks
 * for clips. Holds loading/error state and always replaces (never mutates) the
 * clip list. Any in-flight request is aborted when a new one starts or on unmount.
 */
export function useBrollSuggestions(jobId: string): UseBrollSuggestionsResult {
  const getApiToken = useApiToken();

  const [clips, setClips] = React.useState<readonly BrollClip[]>([]);
  const [status, setStatus] = React.useState<BrollStatus>("idle");
  const [error, setError] = React.useState<string>("");
  const controllerRef = React.useRef<AbortController | null>(null);

  React.useEffect(() => {
    return () => controllerRef.current?.abort();
  }, []);

  const suggest = React.useCallback(
    (params: SuggestBrollParams = {}) => {
      if (!jobId) return;
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      setStatus("loading");
      setError("");

      void (async () => {
        try {
          const token = await getApiToken();
          const result = await suggestBroll(jobId, params, {
            token,
            signal: controller.signal,
          });
          if (controller.signal.aborted) return;
          setClips(result.clips);
          setStatus("ready");
        } catch (err) {
          if (err instanceof DOMException && err.name === "AbortError") return;
          setError(errorMessageOf(err, "Failed to suggest B-roll clips."));
          setStatus("error");
        }
      })();
    },
    [getApiToken, jobId],
  );

  return { clips, status, error, suggest };
}
