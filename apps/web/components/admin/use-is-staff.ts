"use client";

import * as React from "react";
import { getMe } from "@/lib/api";
import { useAuth } from "@/components/auth/clerk-safe";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type StaffStatus = "checking" | "staff" | "denied" | "error";

export interface UseIsStaffResult {
  status: StaffStatus;
  errorMessage: string;
}

/**
 * Whether the signed-in caller is a PLATFORM ADMIN, read from their own
 * `GET /me` (`is_staff`). No staff-only endpoint is probed, so normal users
 * never produce 403s. The admin API still enforces `is_staff` on every call;
 * this only decides whether admin UI is shown. Fails closed.
 */
type ProbeResult = { status: StaffStatus; errorMessage: string };

/**
 * One probe per signed-in user per page load. Both the top bar and the nav
 * menu call this hook on every app page; without the cache a normal user fired
 * two 403s (and a signed-out visitor two 401s) into the console per page.
 * Errors are not cached so a transient failure can be retried on the next mount.
 */
const probeCache = new Map<string, Promise<ProbeResult>>();

async function probeStaff(
  getApiToken: () => Promise<string | undefined>,
): Promise<ProbeResult> {
  try {
    const token = await getApiToken();
    if (!token) return { status: "denied", errorMessage: "" };
    const me = await getMe({ token });
    return { status: me.is_staff === true ? "staff" : "denied", errorMessage: "" };
  } catch (err) {
    return {
      status: "error",
      errorMessage: friendlyErrorMessage(err, "Couldn't verify admin access."),
    };
  }
}

export function useIsStaff(): UseIsStaffResult {
  const getApiToken = useApiToken();
  const { isLoaded, userId } = useAuth();
  const [result, setResult] = React.useState<ProbeResult>({
    status: "checking",
    errorMessage: "",
  });

  React.useEffect(() => {
    if (!isLoaded) return;
    // Signed-out visitors are never staff: no probe, no 401 in the console.
    if (!userId) {
      setResult({ status: "denied", errorMessage: "" });
      return;
    }
    let cancelled = false;
    let probe = probeCache.get(userId);
    if (!probe) {
      probe = probeStaff(getApiToken);
      probeCache.set(userId, probe);
    }
    const key = userId;
    void probe.then((next) => {
      if (next.status === "error") probeCache.delete(key);
      if (!cancelled) setResult(next);
    });
    return () => {
      cancelled = true;
    };
  }, [getApiToken, isLoaded, userId]);

  return result;
}
