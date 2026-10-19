"use client";

import * as React from "react";
import { ApiError, listSocialPlatforms } from "@/lib/api";
import type { SocialPlatform } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type SocialPlatformsStatus = "idle" | "loading" | "ready" | "error";

export interface UseSocialPlatformsResult {
  platforms: readonly SocialPlatform[];
  status: SocialPlatformsStatus;
  error: string;
  reload: () => void;
}

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Loads the supported social-caption platforms (GET /catalog/social-platforms)
 * once `enabled` becomes true. Exposes loading/error state plus a `reload` for
 * the retry affordance. State is only ever replaced, never mutated in place.
 */
export function useSocialPlatforms(
  enabled: boolean,
): UseSocialPlatformsResult {
  const getApiToken = useApiToken();

  const [platforms, setPlatforms] = React.useState<readonly SocialPlatform[]>(
    [],
  );
  const [status, setStatus] = React.useState<SocialPlatformsStatus>("idle");
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
        const list = await listSocialPlatforms({
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setPlatforms(list);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(errorMessageOf(err, "Failed to load platforms."));
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

  return { platforms, status, error, reload };
}
