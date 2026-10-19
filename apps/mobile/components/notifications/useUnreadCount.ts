/**
 * Small hook that owns the bell-badge unread count. Fetches
 * GET /me/notifications/unread_count and refreshes whenever the screen it's
 * mounted on regains focus (e.g. after the user reads notifications and returns
 * to the Me tab). Failures are swallowed to `0` — a badge must never surface an
 * error or block the surface it decorates.
 *
 * The auth token comes from the session and is sent as `x-api-key` by the shared
 * api client. `refresh` is exposed for callers that want to re-poll manually.
 */

import { useCallback, useState } from "react";

import { useFocusEffect } from "expo-router";

import { getUnreadCount, isAbortError } from "@/lib/api";
import { useSession } from "@/src/shared/auth";

export interface UnreadCount {
  /** Current unread count (0 while loading or on any error). */
  count: number;
  /** Re-fetch the count immediately. */
  refresh: () => void;
}

export function useUnreadCount(): UnreadCount {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [count, setCount] = useState(0);

  const load = useCallback(
    (signal?: AbortSignal) => {
      getUnreadCount({ token, signal })
        .then((value) => setCount(value))
        .catch((err: unknown) => {
          // Never surface a badge error. Abort during unmount is expected; on
          // any other transient failure keep the last-known count in place.
          if (isAbortError(err)) return;
        });
    },
    [token],
  );

  // Re-poll on every focus so the badge is fresh when the surface reappears.
  useFocusEffect(
    useCallback(() => {
      const controller = new AbortController();
      load(controller.signal);
      return () => controller.abort();
    }, [load]),
  );

  const refresh = useCallback(() => load(), [load]);

  return { count, refresh };
}
