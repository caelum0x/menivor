"use client";

import * as React from "react";
import { ApiError, generateIdeas } from "@/lib/api";
import type { GenerateIdeasRequest, Idea } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type GenerateStatus = "idle" | "loading" | "ready" | "error";

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

export interface UseGenerateIdeasResult {
  status: GenerateStatus;
  ideas: readonly Idea[];
  errorMessage: string;
  /** The request that produced the current ideas, for a one-click "regenerate". */
  lastRequest: GenerateIdeasRequest | null;
  generate: (req: Readonly<GenerateIdeasRequest>) => Promise<void>;
}

/**
 * Owns the SPARK "generate" lifecycle: POSTs the brief and tracks loading /
 * ready / error state. Concurrent generations are guarded so only the latest
 * request's result is applied (avoids out-of-order responses clobbering state).
 */
export function useGenerateIdeas(): UseGenerateIdeasResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<GenerateStatus>("idle");
  const [ideas, setIdeas] = React.useState<readonly Idea[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [lastRequest, setLastRequest] =
    React.useState<GenerateIdeasRequest | null>(null);
  const runIdRef = React.useRef(0);

  const generate = React.useCallback(
    async (req: Readonly<GenerateIdeasRequest>): Promise<void> => {
      const runId = runIdRef.current + 1;
      runIdRef.current = runId;
      setStatus("loading");
      setErrorMessage("");
      setLastRequest(req);
      try {
        const token = await getApiToken();
        const result = await generateIdeas(req, { token });
        if (runIdRef.current !== runId) return; // superseded
        setIdeas(result);
        setStatus("ready");
      } catch (err) {
        if (runIdRef.current !== runId) return; // superseded
        setErrorMessage(
          errorMessageOf(err, "Couldn't generate ideas. Please try again."),
        );
        setStatus("error");
      }
    },
    [getApiToken],
  );

  return { status, ideas, errorMessage, lastRequest, generate };
}
