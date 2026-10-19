"use client";

import * as React from "react";
import type { ApiKey } from "@/lib/types";
import { ApiError, listApiKeys, revokeApiKey } from "@/lib/api";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type MyApiKeysStatus = "loading" | "ready" | "error";

export interface UseMyApiKeysResult {
  status: MyApiKeysStatus;
  keys: readonly ApiKey[];
  errorMessage: string;
  /** Re-fetch the caller's API keys. */
  reload: () => void;
  /** Optimistically prepend a just-created key (newest first). */
  prepend: (key: ApiKey) => void;
  /**
   * Revoke a key by its row id, marking it revoked in the list on success.
   * Rejects (with the underlying error) so the caller can surface a message.
   */
  revoke: (id: string) => Promise<void>;
}

function messageFor(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

/**
 * Owns the caller's API-key list: loads GET /me/api-keys, exposes an optimistic
 * `prepend` for a newly minted key, and a `revoke` that calls
 * DELETE /me/api-keys/{id}. State is updated immutably (never mutated in place);
 * a revoked key stays in the list flipped to `revoked: true` (a full audit view).
 */
export function useMyApiKeys(): UseMyApiKeysResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<MyApiKeysStatus>("loading");
  const [keys, setKeys] = React.useState<readonly ApiKey[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");

  const reload = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = await getApiToken();
      const result = await listApiKeys({ token });
      setKeys(result);
      setStatus("ready");
    } catch (err) {
      setErrorMessage(
        messageFor(err, "Could not load your API keys. Please try again."),
      );
      setStatus("error");
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const prepend = React.useCallback((key: ApiKey) => {
    setKeys((prev) => [key, ...prev.filter((k) => k.id !== key.id)]);
    setStatus("ready");
  }, []);

  const revoke = React.useCallback(
    async (id: string) => {
      const token = await getApiToken();
      await revokeApiKey(id, { token });
      setKeys((prev) =>
        prev.map((k) => (k.id === id ? { ...k, revoked: true } : k)),
      );
    },
    [getApiToken],
  );

  return {
    status,
    keys,
    errorMessage,
    reload: () => void reload(),
    prepend,
    revoke,
  };
}
