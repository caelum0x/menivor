/**
 * Live-data hook for the navigation hub.
 *
 * Fetches the three signals the hub renders as a summary strip and as
 * contextual badges on nav rows:
 *   - credits + total jobs   (GET /me)
 *   - unread notifications   (GET /me/notifications/unread_count)
 *   - active (non-terminal) jobs (GET /jobs)
 *
 * Each signal is independent: a failure in one does not blank the others. The
 * hook exposes a single `loading`, an `error` (only when EVERYTHING failed so
 * there is nothing to show), and a `reload` for pull-to-refresh.
 */

import { useCallback, useEffect, useState } from "react";

import {
  getUnreadCount,
  isAbortError,
  listJobs,
  me as fetchMe,
} from "@/lib/api";
import { isTerminalState } from "@/lib/types";

/** The resolved live signals. Fields are undefined until first resolved. */
export interface NavHubData {
  credits?: number;
  jobsCount?: number;
  unread?: number;
  activeJobs?: number;
}

export interface NavHubState {
  data: NavHubData;
  loading: boolean;
  /** Set only when every signal failed (nothing to show). */
  error: string | null;
  reload: () => void;
}

export function useNavHubData(token: string | undefined): NavHubState {
  const [data, setData] = useState<NavHubData>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    const signal = controller.signal;
    let active = true;

    setLoading(true);
    setError(null);

    const meP = fetchMe({ token, signal });
    const unreadP = getUnreadCount({ token, signal });
    const jobsP = listJobs({ token, signal });

    void Promise.allSettled([meP, unreadP, jobsP]).then((results) => {
      if (!active) return;

      const [meR, unreadR, jobsR] = results;
      const next: NavHubData = {};

      if (meR.status === "fulfilled") {
        next.credits = meR.value.credits;
        next.jobsCount = meR.value.jobs_count;
      }
      if (unreadR.status === "fulfilled") {
        next.unread = unreadR.value;
      }
      if (jobsR.status === "fulfilled") {
        next.activeJobs = jobsR.value.filter(
          (j) => !isTerminalState(j.state),
        ).length;
      }

      const anyAborted = results.some(
        (r) => r.status === "rejected" && isAbortError(r.reason),
      );
      if (anyAborted) return;

      const allFailed =
        meR.status === "rejected" &&
        unreadR.status === "rejected" &&
        jobsR.status === "rejected";

      setData(next);
      setError(allFailed ? "Couldn't load your live activity." : null);
      setLoading(false);
    });

    return () => {
      active = false;
      controller.abort();
    };
  }, [token, nonce]);

  return { data, loading, error, reload };
}
