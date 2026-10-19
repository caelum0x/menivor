"use client";

import * as React from "react";
import { ApiError, getRetentionPolicy, setRetentionPolicy } from "@/lib/api";
import type { RetentionPolicy, RetentionUpdateRequest } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type RetentionStatus = "loading" | "ready" | "error";

export interface UseRetentionPolicyResult {
  status: RetentionStatus;
  /** The workspace's retention policy, or a keep-forever default. */
  policy: RetentionPolicy | null;
  errorMessage: string;
  /** HTTP status of the last load error (e.g. 403 when the caller lacks settings). */
  errorStatus: number | null;
  /**
   * Replace the workspace's retention window. Resolves to the persisted policy,
   * which replaces local state. Gated by `workspace.settings` server-side.
   */
  save: (body: RetentionUpdateRequest) => Promise<RetentionPolicy>;
  reload: () => void;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Owns a single workspace's data-retention policy
 * (GET/PUT /me/workspaces/{id}/retention). Reading/writing is gated on
 * `workspace.settings` server-side; a caller lacking it surfaces via
 * `errorStatus === 403`. A `null` window means keep-forever. The policy always
 * belongs to the selected workspace alone — no other tenant's data is touched.
 * State is only ever replaced with the server's authoritative value.
 */
export function useRetentionPolicy(
  workspaceId: string | null,
): UseRetentionPolicyResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<RetentionStatus>("loading");
  const [policy, setPolicy] = React.useState<RetentionPolicy | null>(null);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [errorStatus, setErrorStatus] = React.useState<number | null>(null);
  const [reloadNonce, setReloadNonce] = React.useState(0);

  React.useEffect(() => {
    if (!workspaceId) {
      setStatus("ready");
      setPolicy(null);
      setErrorMessage("");
      setErrorStatus(null);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();

    void (async () => {
      setStatus("loading");
      setErrorMessage("");
      setErrorStatus(null);
      try {
        const token = await getApiToken();
        const result = await getRetentionPolicy(workspaceId, {
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setPolicy(result);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setErrorMessage(messageFor(err, "Couldn't load the retention policy."));
        setErrorStatus(err instanceof ApiError ? err.status : null);
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, workspaceId, reloadNonce]);

  const save = React.useCallback(
    async (body: RetentionUpdateRequest): Promise<RetentionPolicy> => {
      if (!workspaceId) throw new Error("No workspace selected.");
      const token = await getApiToken();
      const saved = await setRetentionPolicy(workspaceId, body, { token });
      setPolicy(saved);
      setStatus("ready");
      return saved;
    },
    [getApiToken, workspaceId],
  );

  const reload = React.useCallback(() => setReloadNonce((n) => n + 1), []);

  return { status, policy, errorMessage, errorStatus, save, reload };
}
