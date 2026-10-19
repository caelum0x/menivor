"use client";

import * as React from "react";
import { ApiError, listDubLanguages } from "@/lib/api";
import type { DubLanguage } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type DubLanguagesStatus = "idle" | "loading" | "ready" | "error";

export interface UseDubLanguagesResult {
  languages: readonly DubLanguage[];
  status: DubLanguagesStatus;
  error: string;
  reload: () => void;
}

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Loads the supported dubbing languages (GET /dub/languages) once `enabled`
 * becomes true (e.g. when the dialog opens). Exposes loading/error state and a
 * `reload` for the error retry affordance. State is only ever replaced, never
 * mutated in place.
 */
export function useDubLanguages(enabled: boolean): UseDubLanguagesResult {
  const getApiToken = useApiToken();

  const [languages, setLanguages] = React.useState<readonly DubLanguage[]>([]);
  const [status, setStatus] = React.useState<DubLanguagesStatus>("idle");
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
        const list = await listDubLanguages({
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setLanguages(list);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(errorMessageOf(err, "Failed to load languages."));
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

  return { languages, status, error, reload };
}
