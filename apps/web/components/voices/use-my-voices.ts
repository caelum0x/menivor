"use client";

import * as React from "react";
import type { UserVoice } from "@/lib/types";
import { ApiError, deleteMyVoice, listMyVoices } from "@/lib/api";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type MyVoicesStatus = "loading" | "ready" | "error";

export interface UseMyVoicesResult {
  status: MyVoicesStatus;
  voices: readonly UserVoice[];
  errorMessage: string;
  /** Re-fetch the caller's cloned voices. */
  reload: () => void;
  /** Optimistically prepend a just-cloned voice (newest first). */
  prepend: (voice: UserVoice) => void;
  /** Delete a voice by its row id, updating the list on success. */
  remove: (id: string) => Promise<void>;
}

function messageFor(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

/**
 * Owns the caller's cloned-voice list: loads GET /voices/mine, exposes an
 * optimistic `prepend` for a newly cloned voice, and a `remove` that calls
 * DELETE /voices/mine/{id}. State is updated immutably (never mutated in place).
 */
export function useMyVoices(): UseMyVoicesResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<MyVoicesStatus>("loading");
  const [voices, setVoices] = React.useState<readonly UserVoice[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");

  const reload = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = await getApiToken();
      const result = await listMyVoices({ token });
      setVoices(result);
      setStatus("ready");
    } catch (err) {
      setErrorMessage(
        messageFor(err, "Could not load your brand voices. Please try again."),
      );
      setStatus("error");
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const prepend = React.useCallback((voice: UserVoice) => {
    setVoices((prev) => [voice, ...prev.filter((v) => v.id !== voice.id)]);
    setStatus("ready");
  }, []);

  const remove = React.useCallback(
    async (id: string) => {
      const token = await getApiToken();
      await deleteMyVoice(id, { token });
      setVoices((prev) => prev.filter((v) => v.id !== id));
    },
    [getApiToken],
  );

  return {
    status,
    voices,
    errorMessage,
    reload: () => void reload(),
    prepend,
    remove,
  };
}
