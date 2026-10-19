"use client";

import * as React from "react";
import { getMe } from "@/lib/api";
import { useApiToken } from "@/lib/use-api-token";

/**
 * Resolves the signed-in caller's user id once (GET /me), used to flag "You" in
 * rosters and gate self-actions. Returns `null` until resolved or on failure.
 */
export function useCurrentUserId(): string | null {
  const getApiToken = useApiToken();
  const [userId, setUserId] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const token = await getApiToken();
        const me = await getMe({ token });
        if (!cancelled) setUserId(me.user_id);
      } catch {
        if (!cancelled) setUserId(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getApiToken]);

  return userId;
}
