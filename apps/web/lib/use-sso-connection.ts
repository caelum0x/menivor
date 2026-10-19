"use client";

import * as React from "react";
import {
  ApiError,
  deleteSsoConnection,
  getSsoConnection,
  putSsoConnection,
} from "@/lib/api";
import type { SSOConfigRequest, SSOConnection } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

// Re-exported so the SSO connection fetchers are reachable from this module
// alongside the hook (the page mutates through `save` / `remove` below).
export { putSsoConnection, deleteSsoConnection };

export type SsoConnectionStatus = "loading" | "ready" | "error";

export interface UseSsoConnectionResult {
  status: SsoConnectionStatus;
  /** The workspace's cert-free SSO connection, or `null` when none is configured. */
  connection: SSOConnection | null;
  errorMessage: string;
  /** HTTP status of the last load error (e.g. 403 when the caller lacks settings). */
  errorStatus: number | null;
  /** Persist the connection (PUT). Resolves to the saved cert-free connection. */
  save: (body: SSOConfigRequest) => Promise<SSOConnection>;
  /** Remove the connection (DELETE). Clears local state on success. */
  remove: () => Promise<void>;
  /** Re-fetch the connection. */
  reload: () => void;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Owns a single workspace's Enterprise SSO connection
 * (GET/PUT/DELETE /me/workspaces/{id}/sso). The connection is CERT-FREE — the IdP
 * signing cert / OIDC secret are never returned, only `has_certificate` /
 * `has_client_secret`. Gated by `workspace.settings` server-side; a caller
 * lacking it surfaces via `errorStatus === 403`. State is only ever replaced with
 * the server's authoritative value, never mutated in place. A blank id stays
 * `ready` with `connection: null` (nothing to load).
 */
export function useSsoConnection(
  workspaceId: string | null,
): UseSsoConnectionResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<SsoConnectionStatus>("loading");
  const [connection, setConnection] = React.useState<SSOConnection | null>(null);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [errorStatus, setErrorStatus] = React.useState<number | null>(null);
  const [reloadNonce, setReloadNonce] = React.useState(0);

  React.useEffect(() => {
    if (!workspaceId) {
      setStatus("ready");
      setConnection(null);
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
        const result = await getSsoConnection(workspaceId, {
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setConnection(result);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setErrorMessage(messageFor(err, "Couldn't load the SSO connection."));
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
    async (body: SSOConfigRequest): Promise<SSOConnection> => {
      if (!workspaceId) throw new Error("No workspace selected.");
      const token = await getApiToken();
      const saved = await putSsoConnection(workspaceId, body, { token });
      setConnection(saved);
      setStatus("ready");
      return saved;
    },
    [getApiToken, workspaceId],
  );

  const remove = React.useCallback(async (): Promise<void> => {
    if (!workspaceId) throw new Error("No workspace selected.");
    const token = await getApiToken();
    await deleteSsoConnection(workspaceId, { token });
    setConnection(null);
    setStatus("ready");
  }, [getApiToken, workspaceId]);

  const reload = React.useCallback(() => setReloadNonce((n) => n + 1), []);

  return {
    status,
    connection,
    errorMessage,
    errorStatus,
    save,
    remove,
    reload,
  };
}
