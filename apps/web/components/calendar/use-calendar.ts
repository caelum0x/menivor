"use client";

import * as React from "react";
import { ApiError } from "@/lib/api";
import {
  getCalendar,
  rescheduleEntry,
  type CalendarEntry,
} from "@/lib/calendar";
import { useApiToken } from "@/lib/use-api-token";
import {
  buildDays,
  bucketEntriesByDay,
  rangeForView,
  shiftRef,
  startOfDay,
  type CalendarDay,
  type CalendarView,
} from "@/components/calendar/calendar-month";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type CalendarLoadStatus = "idle" | "loading" | "ready" | "error";

export interface UseCalendarResult {
  view: CalendarView;
  setView: (view: CalendarView) => void;
  /** The reference date the current view is anchored to (local). */
  ref: Date;
  goPrev: () => void;
  goNext: () => void;
  goToday: () => void;
  /** The day cells for the current view. */
  days: readonly CalendarDay[];
  /** Entries grouped by local-day key (see {@link bucketEntriesByDay}). */
  buckets: Map<string, CalendarEntry[]>;
  status: CalendarLoadStatus;
  error: string;
  reload: () => void;
  /** Move a still-pending entry to a new UTC instant. Resolves on success. */
  reschedule: (id: string, scheduledAtISO: string) => Promise<boolean>;
  /** Id currently being rescheduled (for a spinner / disabled state). */
  reschedulingId: string | null;
  rescheduleError: string;
  clearRescheduleError: () => void;
}

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Loads the caller's calendar window (GET /me/calendar) for the current view and
 * exposes month/week navigation plus a `reschedule` mutator (PATCH
 * /me/calendar/{id}). State is only ever replaced, never mutated in place; a
 * successful reschedule swaps the affected entry for the server's returned copy
 * so the grid re-buckets without a full refetch.
 */
export function useCalendar(
  initialView: CalendarView = "month",
): UseCalendarResult {
  const getApiToken = useApiToken();

  const [view, setViewState] = React.useState<CalendarView>(initialView);
  const [ref, setRef] = React.useState<Date>(() => startOfDay(new Date()));
  const [entries, setEntries] = React.useState<readonly CalendarEntry[]>([]);
  const [status, setStatus] = React.useState<CalendarLoadStatus>("idle");
  const [error, setError] = React.useState<string>("");
  const [reloadNonce, setReloadNonce] = React.useState(0);
  const [reschedulingId, setReschedulingId] = React.useState<string | null>(
    null,
  );
  const [rescheduleError, setRescheduleError] = React.useState<string>("");

  const mountedRef = React.useRef(true);
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const refTime = ref.getTime();

  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const { startISO, endISO } = rangeForView(view, new Date(refTime));

    const load = async (): Promise<void> => {
      setStatus("loading");
      setError("");
      try {
        const token = await getApiToken();
        const list = await getCalendar(startISO, endISO, {
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setEntries(list);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(errorMessageOf(err, "Couldn't load your calendar."));
        setStatus("error");
      }
    };

    void load();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, view, refTime, reloadNonce]);

  const days = React.useMemo(
    () => buildDays(view, new Date(refTime)),
    [view, refTime],
  );
  const buckets = React.useMemo(
    () => bucketEntriesByDay(entries),
    [entries],
  );

  const setView = React.useCallback((next: CalendarView) => {
    setViewState(next);
  }, []);

  const goPrev = React.useCallback(() => {
    setRef((prev) => shiftRef(view, prev, -1));
  }, [view]);

  const goNext = React.useCallback(() => {
    setRef((prev) => shiftRef(view, prev, 1));
  }, [view]);

  const goToday = React.useCallback(() => {
    setRef(startOfDay(new Date()));
  }, []);

  const reload = React.useCallback(() => {
    setReloadNonce((n) => n + 1);
  }, []);

  const clearRescheduleError = React.useCallback(() => {
    setRescheduleError("");
  }, []);

  const reschedule = React.useCallback(
    async (id: string, scheduledAtISO: string): Promise<boolean> => {
      setReschedulingId(id);
      setRescheduleError("");
      try {
        const token = await getApiToken();
        const updated = await rescheduleEntry(id, scheduledAtISO, { token });
        if (!mountedRef.current) return true;
        setEntries((prev) =>
          prev.map((entry) => (entry.id === id ? updated : entry)),
        );
        return true;
      } catch (err) {
        if (!mountedRef.current) return false;
        setRescheduleError(
          errorMessageOf(err, "Failed to reschedule this publish."),
        );
        return false;
      } finally {
        if (mountedRef.current) setReschedulingId(null);
      }
    },
    [getApiToken],
  );

  return {
    view,
    setView,
    ref,
    goPrev,
    goNext,
    goToday,
    days,
    buckets,
    status,
    error,
    reload,
    reschedule,
    reschedulingId,
    rescheduleError,
    clearRescheduleError,
  };
}
