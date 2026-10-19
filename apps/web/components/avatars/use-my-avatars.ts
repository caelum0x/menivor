"use client";

import * as React from "react";
import type { Avatar } from "@/lib/types";
import { isCustomAvatar } from "@/lib/types";
import { ApiError, listAvatars } from "@/lib/api";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type MyAvatarsStatus = "loading" | "ready" | "error";

export interface UseMyAvatarsResult {
  status: MyAvatarsStatus;
  avatars: readonly Avatar[];
  errorMessage: string;
  /** Re-fetch GET /avatars and re-filter to the caller's custom avatars. */
  reload: () => void;
  /** Optimistically prepend a just-created custom avatar (newest first). */
  prepend: (avatar: Avatar) => void;
}

function messageFor(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

/**
 * Owns the caller's CUSTOM photo→avatar list. GET /avatars returns the merged
 * catalog (curated provider avatars + stored presets), so this hook filters to
 * the presets (see {@link isCustomAvatar}) and exposes an optimistic `prepend`
 * for a newly created avatar. State is updated immutably (never mutated in
 * place).
 */
export function useMyAvatars(): UseMyAvatarsResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<MyAvatarsStatus>("loading");
  const [avatars, setAvatars] = React.useState<readonly Avatar[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");

  const reload = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = await getApiToken();
      const all = await listAvatars({ token });
      setAvatars(all.filter(isCustomAvatar));
      setStatus("ready");
    } catch (err) {
      setErrorMessage(
        messageFor(err, "Could not load your avatars. Please try again."),
      );
      setStatus("error");
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const prepend = React.useCallback((avatar: Avatar) => {
    setAvatars((prev) => [
      avatar,
      ...prev.filter((a) => a.avatar_id !== avatar.avatar_id),
    ]);
    setStatus("ready");
  }, []);

  return {
    status,
    avatars,
    errorMessage,
    reload: () => void reload(),
    prepend,
  };
}
