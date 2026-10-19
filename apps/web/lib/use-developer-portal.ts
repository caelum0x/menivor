"use client";

import * as React from "react";
import { ApiError, getDeveloperPortal } from "@/lib/api";
import type { DeveloperPortal } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type DeveloperPortalStatus = "loading" | "ready" | "error";

export interface UseDeveloperPortalResult {
  status: DeveloperPortalStatus;
  /** The caller-scoped portal summary, or `null` until loaded. */
  portal: DeveloperPortal | null;
  errorMessage: string;
  /** Re-fetch the developer-portal summary. */
  reload: () => void;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Loads the caller-scoped developer-portal summary (GET /me/developer): API-key
 * + webhook footprints, workspace count, and static integration links. READ-only
 * and secret-free; state is replaced, never mutated in place.
 */
export function useDeveloperPortal(): UseDeveloperPortalResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<DeveloperPortalStatus>("loading");
  const [portal, setPortal] = React.useState<DeveloperPortal | null>(null);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [reloadNonce, setReloadNonce] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    void (async () => {
      setStatus("loading");
      setErrorMessage("");
      try {
        const token = await getApiToken();
        const result = await getDeveloperPortal({
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setPortal(result);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setErrorMessage(
          messageFor(err, "Couldn't load your developer portal."),
        );
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, reloadNonce]);

  const reload = React.useCallback(() => setReloadNonce((n) => n + 1), []);

  return { status, portal, errorMessage, reload };
}
