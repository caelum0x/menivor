/**
 * Whether the signed-in account is a Menivor platform admin (`is_staff`).
 *
 * `/me` does not expose the staff flag, so this asks the server directly with
 * the cheapest staff-only read (GET /admin/users?limit=1): 200 means staff, 403
 * means a regular creator. The answer is cached per session key for the life of
 * the app so menus do not re-probe on every render. Any other failure (offline,
 * 5xx) is treated as "not admin" and retried on the next mount; admin surfaces
 * stay hidden rather than flashing into a consumer menu.
 */

import { useEffect, useState } from "react";

import { ApiError, adminListUsers } from "@/lib/api";
import { useSession } from "@/src/shared/auth";

const adminCache = new Map<string, boolean>();

export function usePlatformAdmin(): boolean {
  const { apiKey } = useSession();
  const [isAdmin, setIsAdmin] = useState<boolean>(() =>
    apiKey ? adminCache.get(apiKey) === true : false,
  );

  useEffect(() => {
    if (!apiKey) {
      setIsAdmin(false);
      return undefined;
    }
    const cached = adminCache.get(apiKey);
    if (cached !== undefined) {
      setIsAdmin(cached);
      return undefined;
    }
    const controller = new AbortController();
    adminListUsers({ limit: 1 }, { token: apiKey, signal: controller.signal })
      .then(() => {
        adminCache.set(apiKey, true);
        setIsAdmin(true);
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          adminCache.set(apiKey, false);
        }
        if (!controller.signal.aborted) setIsAdmin(false);
      });
    return () => controller.abort();
  }, [apiKey]);

  return isAdmin;
}
