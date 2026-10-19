"use client";

import * as React from "react";
import { ApiError, listCoverStyles } from "@/lib/api";
import type { CoverStyle } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type CoverStylesStatus = "idle" | "loading" | "ready" | "error";

export interface UseCoverStylesResult {
  styles: readonly CoverStyle[];
  status: CoverStylesStatus;
  error: string;
  reload: () => void;
}

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Loads the available cover styles (GET /catalog/cover-styles) once `enabled`
 * becomes true. Exposes loading/error state plus a `reload` for the retry
 * affordance. State is only ever replaced, never mutated in place.
 */
export function useCoverStyles(enabled: boolean): UseCoverStylesResult {
  const getApiToken = useApiToken();

  const [styles, setStyles] = React.useState<readonly CoverStyle[]>([]);
  const [status, setStatus] = React.useState<CoverStylesStatus>("idle");
  const [error, setError] = React.useState<string>("");
  const [reloadNonce, setReloadNonce] = React.useState(0);

  React.useEffect(() => {
    if (!enabled) return;

    let cancelled = false;
    const controller = new AbortController();

    const load = async (): Promise<void> => {
      setStatus("loading");
      setError("");
      try {
        const token = await getApiToken();
        const list = await listCoverStyles({
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setStyles(list);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(errorMessageOf(err, "Failed to load cover styles."));
        setStatus("error");
      }
    };

    void load();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [enabled, getApiToken, reloadNonce]);

  const reload = React.useCallback(() => {
    setReloadNonce((n) => n + 1);
  }, []);

  return { styles, status, error, reload };
}
