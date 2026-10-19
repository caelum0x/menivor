"use client";

import * as React from "react";
import { ApiError, getSecurityPolicy, putSecurityPolicy } from "@/lib/api";
import type { SecurityPolicy, SecurityPolicyRequest } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

// Re-exported so the security-policy write fetcher is reachable from this module
// alongside the hook (the page mutates through `save` below).
export { putSecurityPolicy };

export type SecurityPolicyStatus = "loading" | "ready" | "error";

export interface UseSecurityPolicyResult {
  status: SecurityPolicyStatus;
  /** The workspace's security policy, or `null` when none is configured yet. */
  policy: SecurityPolicy | null;
  errorMessage: string;
  /** HTTP status of the last load error (e.g. 403 when the caller lacks settings). */
  errorStatus: number | null;
  /**
   * Apply a PARTIAL policy update (only supplied fields change). Resolves to the
   * persisted policy, which replaces local state.
   */
  save: (body: SecurityPolicyRequest) => Promise<SecurityPolicy>;
  /** Re-fetch the workspace's policy. */
  reload: () => void;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Owns a single workspace's login security policy
 * (GET/PUT /me/workspaces/{id}/security). The policy is cert-free / secret-free.
 * `save` performs a PARTIAL update — only the supplied fields change. Gated by
 * `workspace.settings` server-side; a caller lacking it surfaces via
 * `errorStatus === 403`. State is only ever replaced with the server's
 * authoritative value, never mutated in place.
 */
export function useSecurityPolicy(
  workspaceId: string | null,
): UseSecurityPolicyResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<SecurityPolicyStatus>("loading");
  const [policy, setPolicy] = React.useState<SecurityPolicy | null>(null);
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
        const result = await getSecurityPolicy(workspaceId, {
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setPolicy(result);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setErrorMessage(messageFor(err, "Couldn't load the security policy."));
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
    async (body: SecurityPolicyRequest): Promise<SecurityPolicy> => {
      if (!workspaceId) throw new Error("No workspace selected.");
      const token = await getApiToken();
      const saved = await putSecurityPolicy(workspaceId, body, { token });
      setPolicy(saved);
      setStatus("ready");
      return saved;
    },
    [getApiToken, workspaceId],
  );

  const reload = React.useCallback(() => setReloadNonce((n) => n + 1), []);

  return { status, policy, errorMessage, errorStatus, save, reload };
}
