"use client";

import * as React from "react";
import {
  ApiError,
  createScimToken,
  listScimTokens,
  revokeScimToken,
} from "@/lib/api";
import type { ScimToken } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

// Re-exported so the SCIM token fetchers are reachable from this module
// alongside the hook (the page mutates through `create` / `revoke` below).
export { createScimToken, revokeScimToken };

export type ScimTokensStatus = "loading" | "ready" | "error";

export interface UseScimTokensResult {
  status: ScimTokensStatus;
  /** The workspace's SCIM tokens (never a raw token — only ids/prefixes/status). */
  tokens: readonly ScimToken[];
  errorMessage: string;
  /** HTTP status of the last load error (e.g. 403 when the caller lacks settings). */
  errorStatus: number | null;
  /**
   * Mint a new SCIM bearer token. Resolves to the created token WITH its one-time
   * raw `token` value (shown once, then unrecoverable). The listing is updated
   * optimistically with the non-secret descriptor.
   */
  create: () => Promise<ScimToken>;
  /** Revoke a token by id; flips it to `revoked: true` in the list on success. */
  revoke: (tokenId: string) => Promise<void>;
  /** Re-fetch the workspace's tokens. */
  reload: () => void;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Owns a single workspace's SCIM bearer tokens
 * (GET/POST/DELETE /me/workspaces/{id}/scim/tokens). A minted token's raw value
 * is returned EXACTLY ONCE (the caller reveals it, then it is unrecoverable); the
 * list never carries a raw secret. Gated by `workspace.settings` server-side; a
 * caller lacking it surfaces via `errorStatus === 403`. State is updated
 * immutably — a revoked token stays in the list flipped to `revoked: true`.
 */
export function useScimTokens(workspaceId: string | null): UseScimTokensResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<ScimTokensStatus>("loading");
  const [tokens, setTokens] = React.useState<readonly ScimToken[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [errorStatus, setErrorStatus] = React.useState<number | null>(null);
  const [reloadNonce, setReloadNonce] = React.useState(0);

  React.useEffect(() => {
    if (!workspaceId) {
      setStatus("ready");
      setTokens([]);
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
        const result = await listScimTokens(workspaceId, {
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setTokens(result);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setErrorMessage(messageFor(err, "Couldn't load the SCIM tokens."));
        setErrorStatus(err instanceof ApiError ? err.status : null);
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, workspaceId, reloadNonce]);

  const create = React.useCallback(async (): Promise<ScimToken> => {
    if (!workspaceId) throw new Error("No workspace selected.");
    const token = await getApiToken();
    const created = await createScimToken(workspaceId, { token });
    // Reflect the new token in the list immediately WITHOUT its raw secret.
    const listItem: ScimToken = { ...created, token: null };
    setTokens((prev) => [listItem, ...prev.filter((t) => t.id !== created.id)]);
    setStatus("ready");
    return created;
  }, [getApiToken, workspaceId]);

  const revoke = React.useCallback(
    async (tokenId: string): Promise<void> => {
      if (!workspaceId) throw new Error("No workspace selected.");
      const token = await getApiToken();
      await revokeScimToken(workspaceId, tokenId, { token });
      setTokens((prev) =>
        prev.map((t) => (t.id === tokenId ? { ...t, revoked: true } : t)),
      );
    },
    [getApiToken, workspaceId],
  );

  const reload = React.useCallback(() => setReloadNonce((n) => n + 1), []);

  return { status, tokens, errorMessage, errorStatus, create, revoke, reload };
}
