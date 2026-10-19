/**
 * Tiny async-resource hook for the Me sections. Owns the loading / ready /
 * error lifecycle for a single GET, exposes an idempotent `reload`, and lets
 * callers apply optimistic updates via `setData` (used by the presets list for
 * create/delete before the network settles).
 *
 * The `fetcher` MUST be memoised by the caller (e.g. `useCallback` keyed on the
 * auth token); the hook reloads whenever the fetcher identity changes.
 */

import { useCallback, useEffect, useState } from "react";

import { isAbortError } from "@/lib/api";
import { describeError } from "./errors";

export type ResourceStatus = "loading" | "ready" | "error";

export interface Resource<T> {
  status: ResourceStatus;
  data: T | null;
  error: string;
  reload: () => void;
  setData: (updater: (prev: T | null) => T | null) => void;
}

export function useResource<T>(fetcher: () => Promise<T>): Resource<T> {
  const [status, setStatus] = useState<ResourceStatus>("loading");
  const [data, setDataState] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  const setData = useCallback((updater: (prev: T | null) => T | null) => {
    setDataState((prev) => updater(prev));
  }, []);

  useEffect(() => {
    let active = true;
    setStatus("loading");
    setError("");

    fetcher()
      .then((result) => {
        if (!active) return;
        setDataState(result);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (!active || isAbortError(err)) return;
        setError(describeError(err, "Failed to load."));
        setStatus("error");
      });

    return () => {
      active = false;
    };
    // `nonce` forces a re-run on reload(); `fetcher` re-runs on token change.
  }, [fetcher, nonce]);

  return { status, data, error, reload, setData };
}
