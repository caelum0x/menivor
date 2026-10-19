"use client";

import * as React from "react";
import { useApiToken } from "@/lib/use-api-token";
import {
  bucketEntriesByDay,
  buildDays,
  rangeForView,
  shiftRef,
  startOfDay,
  type CalendarDay,
  type CalendarView,
} from "@/components/calendar/calendar-month";
import {
  conflictCheckOf,
  errorMessage,
  getBoard,
  moveEntry,
  type BoardEntry,
  type SlotCheck,
} from "@/components/calendar/board-api";

export type BoardLoadStatus = "idle" | "loading" | "ready" | "error";

/** A refused move: the entry snapped back; the creator can take the suggestion or keep the slot. */
export interface MoveConflict {
  entry: BoardEntry;
  attemptedISO: string;
  check: SlotCheck;
}

export interface MoveNotice {
  tone: "info" | "error";
  message: string;
}

export function entryKey(entry: Pick<BoardEntry, "source" | "id">): string {
  return `${entry.source}:${entry.id}`;
}

/** The same local time-of-day as `iso`, on the local day `day`. */
export function sameTimeOnDay(iso: string, day: Date): Date {
  const original = new Date(iso);
  return new Date(
    day.getFullYear(),
    day.getMonth(),
    day.getDate(),
    original.getHours(),
    original.getMinutes(),
  );
}

/**
 * The unified calendar board: every scheduled/published post in the visible
 * window (native reels + extended platforms + channels), with a policy-checked
 * `move`. Moves are optimistic; a refused slot snaps the entry back and exposes
 * a {@link MoveConflict} (reason + suggested slot). State is only ever replaced.
 */
export function useCalendarBoard(initialView: CalendarView = "month") {
  const getApiToken = useApiToken();
  const [view, setView] = React.useState<CalendarView>(initialView);
  const [ref, setRef] = React.useState<Date>(() => startOfDay(new Date()));
  const [entries, setEntries] = React.useState<readonly BoardEntry[]>([]);
  const [bestHours, setBestHours] = React.useState<Record<string, number[]>>({});
  const [status, setStatus] = React.useState<BoardLoadStatus>("idle");
  const [error, setError] = React.useState("");
  const [nonce, setNonce] = React.useState(0);
  const [movingKey, setMovingKey] = React.useState<string | null>(null);
  const [conflict, setConflict] = React.useState<MoveConflict | null>(null);
  const [notice, setNotice] = React.useState<MoveNotice | null>(null);

  const mounted = React.useRef(true);
  React.useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const refTime = ref.getTime();

  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const { startISO, endISO } = rangeForView(view, new Date(refTime));
    const load = async () => {
      setStatus("loading");
      setError("");
      try {
        const token = await getApiToken();
        const data = await getBoard(startISO, endISO, {
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setEntries(data.entries);
        setBestHours(data.best_hours_utc);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(errorMessage(err, "Couldn't load your calendar."));
        setStatus("error");
      }
    };
    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, view, refTime, nonce]);

  const days: readonly CalendarDay[] = React.useMemo(
    () => buildDays(view, new Date(refTime)),
    [view, refTime],
  );
  const buckets = React.useMemo(() => bucketEntriesByDay(entries), [entries]);

  const replaceEntry = React.useCallback((next: BoardEntry) => {
    setEntries((prev) =>
      prev.map((e) => (entryKey(e) === entryKey(next) ? next : e)),
    );
  }, []);

  const move = React.useCallback(
    async (entry: BoardEntry, scheduledAtISO: string, force = false): Promise<boolean> => {
      const key = entryKey(entry);
      if (new Date(scheduledAtISO).getTime() <= Date.now()) {
        setNotice({ tone: "error", message: "That time has already passed. Pick a later slot." });
        return false;
      }
      setConflict(null);
      setNotice(null);
      setMovingKey(key);
      // Optimistic: show the entry in its new slot while the server checks the policy.
      replaceEntry({ ...entry, scheduled_at: scheduledAtISO });
      try {
        const token = await getApiToken();
        const result = await moveEntry(entry, scheduledAtISO, force, { token });
        if (!mounted.current) return true;
        replaceEntry(result.entry);
        if (result.forced) {
          setNotice({
            tone: "info",
            message: `Kept anyway: ${result.check.reason}`,
          });
        }
        return true;
      } catch (err) {
        if (!mounted.current) return false;
        replaceEntry(entry); // snap back
        const check = conflictCheckOf(err);
        if (check) {
          setConflict({ entry, attemptedISO: scheduledAtISO, check });
        } else {
          setNotice({
            tone: "error",
            message: errorMessage(err, "Couldn't move this post."),
          });
        }
        return false;
      } finally {
        if (mounted.current) setMovingKey(null);
      }
    },
    [getApiToken, replaceEntry],
  );

  const moveToDay = React.useCallback(
    (key: string, day: Date) => {
      const entry = entries.find((e) => entryKey(e) === key);
      if (!entry || !entry.can_move || !entry.scheduled_at) return;
      const target = sameTimeOnDay(entry.scheduled_at, day);
      if (target.toISOString() === new Date(entry.scheduled_at).toISOString()) return;
      void move(entry, target.toISOString());
    },
    [entries, move],
  );

  return {
    view,
    setView,
    ref,
    goPrev: () => setRef((prev) => shiftRef(view, prev, -1)),
    goNext: () => setRef((prev) => shiftRef(view, prev, 1)),
    goToday: () => setRef(startOfDay(new Date())),
    days,
    buckets,
    entries,
    bestHours,
    status,
    error,
    reload: () => setNonce((n) => n + 1),
    move,
    moveToDay,
    movingKey,
    conflict,
    clearConflict: () => setConflict(null),
    notice,
    clearNotice: () => setNotice(null),
  };
}

export type CalendarBoard = ReturnType<typeof useCalendarBoard>;
