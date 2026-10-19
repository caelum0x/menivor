"use client";

import * as React from "react";
import { JobState, type JobStateValue } from "@reelforge/api-contract";

import { ApiError, POLL_INTERVAL_MS } from "@/src/shared/api";
import { useApiToken } from "@/lib/use-api-token";
import {
  getBrollClip,
  listBrollClips,
  listBrollPresets,
  type BrollClip,
  type BrollPreset,
} from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** Coarse lifecycle bucket used by the library's filter chips. */
export type BrollClipPhase = "ready" | "processing" | "failed";

/** Filter selector value: a phase, or `all` for the unfiltered library. */
export type BrollLibraryFilter = "all" | BrollClipPhase;

export interface UseBrollLibraryResult {
  /** The caller's clips, newest first, filtered by {@link filter}. */
  clips: readonly BrollClip[];
  /** Curated/owned motion presets that can seed a new studio generation. */
  presets: readonly BrollPreset[];
  loading: boolean;
  errorMessage: string;
  /** Presets are DB-backed and best-effort; a failure never breaks the gallery. */
  presetsError: string;
  filter: BrollLibraryFilter;
  setFilter: (filter: BrollLibraryFilter) => void;
  /** Count of clips in each phase across the UNFILTERED library (for chip badges). */
  counts: Record<BrollLibraryFilter, number>;
  /** Re-fetch clips + presets from the API. */
  refresh: () => Promise<void>;
}

/** Map a clip's job state to its coarse library phase. */
export function clipPhase(state: JobStateValue): BrollClipPhase {
  if (state === JobState.Complete) return "ready";
  if (state === JobState.Failed) return "failed";
  return "processing";
}

function isTerminal(state: JobStateValue): boolean {
  return state === JobState.Complete || state === JobState.Failed;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Owns the authenticated caller's B-roll clip library: loads durable clip
 * history + the preset catalog from the existing `/generation/broll/*` routes,
 * lets the UI filter by lifecycle phase, and polls any still-processing clip at
 * {@link POLL_INTERVAL_MS} until it reaches a terminal state — replacing its
 * snapshot with the server's authoritative value each tick. A page refresh
 * rehydrates from the API rather than trusting browser memory as history.
 */
export function useBrollLibrary(): UseBrollLibraryResult {
  const getApiToken = useApiToken();
  const [clips, setClips] = React.useState<readonly BrollClip[]>([]);
  const [presets, setPresets] = React.useState<readonly BrollPreset[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [presetsError, setPresetsError] = React.useState("");
  const [filter, setFilter] = React.useState<BrollLibraryFilter>("all");

  const load = React.useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setErrorMessage("");
      const token = await getApiToken();
      try {
        const list = await listBrollClips({}, { token, signal });
        if (!signal?.aborted) setClips(list);
      } catch (err) {
        if (signal?.aborted) return;
        setErrorMessage(messageFor(err, "Failed to load your B-roll library."));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
      // Presets are best-effort and DB-backed: a failure degrades the preset
      // strip but must never blank out the clip gallery.
      try {
        const list = await listBrollPresets({ token, signal });
        if (!signal?.aborted) setPresets(list);
      } catch (err) {
        if (signal?.aborted) return;
        setPresetsError(messageFor(err, "Presets unavailable."));
      }
    },
    [getApiToken],
  );

  React.useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const refresh = React.useCallback(async () => {
    await load();
  }, [load]);

  // Immutable upsert: replace the matching snapshot in place.
  const upsert = React.useCallback((next: BrollClip) => {
    setClips((prev) => {
      const idx = prev.findIndex((c) => c.generation_id === next.generation_id);
      if (idx === -1) return prev;
      const copy = prev.slice();
      copy[idx] = next;
      return copy;
    });
  }, []);

  // Poll every non-terminal clip on a shared interval. The effect re-runs
  // whenever the set of pending ids changes, so completed clips stop polling.
  const pendingIds = clips
    .filter((c) => !isTerminal(c.state))
    .map((c) => c.generation_id)
    .join(",");

  React.useEffect(() => {
    if (!pendingIds) return;
    const ids = pendingIds.split(",");
    const controller = new AbortController();
    let cancelled = false;

    const timer = setInterval(() => {
      void (async () => {
        const token = await getApiToken();
        for (const id of ids) {
          try {
            const snapshot = await getBrollClip(id, {
              token,
              signal: controller.signal,
            });
            if (!cancelled) upsert(snapshot);
          } catch (err) {
            if (err instanceof DOMException && err.name === "AbortError") return;
            // Best-effort poll: a transient error is retried next tick.
          }
        }
      })();
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      controller.abort();
      clearInterval(timer);
    };
  }, [pendingIds, getApiToken, upsert]);

  const counts = React.useMemo<Record<BrollLibraryFilter, number>>(() => {
    const base: Record<BrollLibraryFilter, number> = {
      all: clips.length,
      ready: 0,
      processing: 0,
      failed: 0,
    };
    for (const clip of clips) base[clipPhase(clip.state)] += 1;
    return base;
  }, [clips]);

  const filtered = React.useMemo(() => {
    if (filter === "all") return clips;
    return clips.filter((c) => clipPhase(c.state) === filter);
  }, [clips, filter]);

  return {
    clips: filtered,
    presets,
    loading,
    errorMessage,
    presetsError,
    filter,
    setFilter,
    counts,
    refresh,
  };
}
