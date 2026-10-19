"use client";

import * as React from "react";
import { ApiError } from "@/lib/api";
import {
  listAvatars,
  listCaptionStyles,
  listCoverStyles,
  listHooks,
  listLayouts,
  listMusic,
  listTemplates,
  listVoices,
} from "@/lib/api";
import type { RequestOptions } from "@/src/shared/api";
import type {
  Avatar,
  CaptionStyle,
  CoverStyle,
  HookCatalog,
  LayoutOption,
  MusicTrack,
  Template,
  Voice,
} from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type ResourceStatus = "loading" | "ready" | "error";

export interface UseResourceResult<T> {
  status: ResourceStatus;
  data: T | null;
  error: string;
  reload: () => void;
}

function messageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Loads a read-only backend resource once on mount (and on demand via `reload`),
 * threading the caller's Clerk token through the shared API client. `fetcher`
 * MUST be a stable module-level reference (the exported `lib/api` functions are).
 * State is always replaced, never mutated in place.
 */
export function useApiResource<T>(
  fetcher: (options?: RequestOptions) => Promise<T>,
  fallback: string,
): UseResourceResult<T> {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<ResourceStatus>("loading");
  const [data, setData] = React.useState<T | null>(null);
  const [error, setError] = React.useState<string>("");
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const load = async (): Promise<void> => {
      setStatus("loading");
      setError("");
      try {
        const token = await getApiToken();
        const result = await fetcher({ token, signal: controller.signal });
        if (cancelled) return;
        setData(result);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(messageOf(err, fallback));
        setStatus("error");
      }
    };

    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [fetcher, fallback, getApiToken, nonce]);

  const reload = React.useCallback(() => setNonce((n) => n + 1), []);

  return { status, data, error, reload };
}

export function useCaptionStyles(): UseResourceResult<CaptionStyle[]> {
  return useApiResource(listCaptionStyles, "Could not load caption styles.");
}

export function useMusic(): UseResourceResult<MusicTrack[]> {
  return useApiResource(listMusic, "Could not load the music library.");
}

export function useLayouts(): UseResourceResult<LayoutOption[]> {
  return useApiResource(listLayouts, "Could not load composition layouts.");
}

export function useTemplates(): UseResourceResult<Template[]> {
  return useApiResource(listTemplates, "Could not load templates.");
}

export function useHookCatalog(): UseResourceResult<HookCatalog> {
  return useApiResource(listHooks, "Could not load the hook catalog.");
}

export function useCoverStylesCatalog(): UseResourceResult<CoverStyle[]> {
  return useApiResource(listCoverStyles, "Could not load cover styles.");
}

export function useAvatarsCatalog(): UseResourceResult<Avatar[]> {
  return useApiResource(listAvatars, "Could not load the avatar gallery.");
}

export function useVoicesCatalog(): UseResourceResult<Voice[]> {
  return useApiResource(listVoices, "Could not load the voice gallery.");
}
