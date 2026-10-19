/**
 * Typed fetch client for the ReelForge Publishing Calendar API.
 *
 * These endpoints back the creator's publishing CALENDAR — a month/week grid of
 * their scheduled + already-published reels — and let them RESCHEDULE a still-
 * `pending` publish to a new future UTC time. They are strictly owner-scoped
 * server-side and all times are UTC ISO-8601 instants (the UI renders them in
 * the creator's local timezone).
 *
 * This is a NEW module, intentionally disjoint from `@/lib/api` (which a
 * concurrent workflow owns). It reuses the exported `API_BASE` + `ApiError` +
 * `RequestOptions` from that module but replicates the small `request<T>()`
 * envelope-unwrapping helper locally so it never has to be edited there. No
 * secrets are hardcoded: auth is the caller's Clerk JWT (or, as a fallback, the
 * public browser-exposed `NEXT_PUBLIC_APP_API_KEY`).
 */

import { API_BASE, ApiError, type RequestOptions } from "@/lib/api";
import type { PublishPlatform, ScheduledPublishStatus } from "@/lib/types";

/** Public app-level API key (non-secret; browser-exposed by design). */
const APP_API_KEY: string = process.env.NEXT_PUBLIC_APP_API_KEY || "";

/**
 * One calendar entry — the safe, render-only projection of a scheduled publish.
 * Mirrors the backend's `CalendarEntryModel` (exactly these five fields; never
 * `user_id` / `result` / `error` / financials).
 */
export interface CalendarEntry {
  /** Server row id — pass to {@link rescheduleEntry} / cancel. */
  id: string;
  /** The finished reel this schedule publishes (may be absent). */
  job_id: string | null;
  /** Target platforms. */
  platforms: PublishPlatform[];
  /** ISO-8601 UTC instant the reel is scheduled to auto-publish at. */
  scheduled_at: string | null;
  /** Current lifecycle status. */
  status: ScheduledPublishStatus;
}

/** The standard `{ status, data, message }` envelope the backend returns. */
interface ApiEnvelope<T> {
  status?: number;
  data?: T;
  message?: string;
}

function buildHeaders(
  token: string | undefined,
  hasBody: boolean,
): Record<string, string> {
  const headers: Record<string, string> = {};
  const key = token || APP_API_KEY;
  if (key) headers["x-api-key"] = key;
  if (hasBody) headers["Content-Type"] = "application/json";
  return headers;
}

/**
 * Core request helper — unwraps the `{ status, data, message }` envelope and
 * throws an {@link ApiError} for any non-2xx response or network failure. Kept
 * local to this module (mirrors the private helper in `@/lib/api`).
 */
async function request<T>(
  path: string,
  init: {
    method?: string;
    body?: unknown;
    options?: RequestOptions;
  } = {},
): Promise<T> {
  const { method = "GET", body, options } = init;
  const hasBody = body !== undefined;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: buildHeaders(options?.token, hasBody),
      body: hasBody ? JSON.stringify(body) : undefined,
      signal: options?.signal,
      cache: "no-store",
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(
      `Network error contacting the API: ${
        err instanceof Error ? err.message : String(err)
      }`,
      0,
      err,
    );
  }

  let envelope: ApiEnvelope<T> | null = null;
  const raw = await res.text();
  if (raw) {
    try {
      envelope = JSON.parse(raw) as ApiEnvelope<T>;
    } catch {
      envelope = null;
    }
  }

  if (!res.ok) {
    const message =
      envelope?.message ||
      `Request failed with status ${res.status} ${res.statusText}`.trim();
    throw new ApiError(message, res.status, envelope ?? raw);
  }

  if (envelope === null) {
    throw new ApiError(
      "Malformed response: expected a JSON envelope from the API.",
      res.status,
      raw,
    );
  }

  return (envelope.data ?? (envelope as unknown as T)) as T;
}

// ---------------------------------------------------------------------------
// Normalization — the API is a system boundary; never trust the shape.
// ---------------------------------------------------------------------------

/** Coerce a raw record into a fully-populated {@link CalendarEntry}. */
function normalizeEntry(raw: unknown): CalendarEntry | null {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  const id = typeof record.id === "string" ? record.id : "";
  if (!id) return null;

  const platforms = Array.isArray(record.platforms)
    ? record.platforms.filter(
        (p): p is PublishPlatform => typeof p === "string" && p.length > 0,
      )
    : [];

  return {
    id,
    job_id: typeof record.job_id === "string" ? record.job_id : null,
    platforms,
    scheduled_at:
      typeof record.scheduled_at === "string" ? record.scheduled_at : null,
    status:
      typeof record.status === "string"
        ? (record.status as ScheduledPublishStatus)
        : "pending",
  };
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

/**
 * GET /me/calendar?start=&end= — the caller's scheduled + already-published
 * reels whose `scheduled_at` falls in the `[startISO, endISO]` UTC window (both
 * ISO-8601). Strictly owner-scoped server-side; the backend clamps an over-wide
 * window (max ~92 days) and rejects an inverted / empty / unparseable range with
 * a `400` (surfaced as {@link ApiError}). The backend may return the list
 * directly as `data` or wrapped as `{ entries: [...] }`; both shapes are
 * normalized to a `CalendarEntry[]`, and malformed rows are dropped.
 */
export async function getCalendar(
  startISO: string,
  endISO: string,
  options?: RequestOptions,
): Promise<CalendarEntry[]> {
  const query = new URLSearchParams({ start: startISO, end: endISO });
  const data = await request<CalendarEntry[] | { entries?: CalendarEntry[] }>(
    `/me/calendar?${query.toString()}`,
    { options },
  );
  const list = Array.isArray(data) ? data : (data?.entries ?? []);
  return list
    .map(normalizeEntry)
    .filter((entry): entry is CalendarEntry => entry !== null);
}

/**
 * PATCH /me/calendar/{id} — move a still-`pending` schedule the caller owns to
 * `scheduledAtISO` (a future ISO-8601 UTC instant). Ownership + the pending-only
 * rule are enforced server-side: an unknown/foreign id is a `404`, a non-pending
 * row (or a lost race with the due-runner) a `409`, and a missing/unparseable/
 * past time a `400` — all surfaced as {@link ApiError}. Returns the moved entry.
 */
export async function rescheduleEntry(
  scheduleId: string,
  scheduledAtISO: string,
  options?: RequestOptions,
): Promise<CalendarEntry> {
  const data = await request<CalendarEntry>(
    `/me/calendar/${encodeURIComponent(scheduleId)}`,
    { method: "PATCH", body: { scheduled_at: scheduledAtISO }, options },
  );
  const entry = normalizeEntry(data);
  if (!entry) {
    throw new ApiError(
      "Malformed response: expected the rescheduled entry.",
      200,
      data,
    );
  }
  return entry;
}
