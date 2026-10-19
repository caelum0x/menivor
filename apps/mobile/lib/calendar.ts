/**
 * Typed fetch client for the ReelForge Publishing CALENDAR endpoints
 * (`app/controllers/v1/calendar.py`). This is the React Native / Expo mirror of
 * `web/lib/calendar.ts` — same routes, same envelope handling, same owner-scoped
 * shapes.
 *
 * Kept as a SEPARATE module from `lib/api.ts` on purpose (the calendar feature is
 * self-contained). It reuses the shared primitives that `lib/api.ts` already
 * exports — `API_BASE`, `ApiError`, `isAbortError`, `RequestOptions` — but owns a
 * small request helper so it never has to touch `lib/api.ts`.
 *
 * Auth: every request sends an `x-api-key` header — either an explicit per-call
 * token (the signed-in user's key from the session) or, as a fallback, the public
 * app key from `EXPO_PUBLIC_APP_API_KEY`. No secrets are hardcoded here.
 *
 * All times crossing this boundary are ISO-8601 UTC; screens render them in the
 * creator's own timezone.
 */

import {
  API_BASE,
  ApiError,
  isAbortError,
  type RequestOptions,
} from "./api";
import type { ApiEnvelope } from "./types";

/** Public app-level API key (non-secret; shipped in the bundle by design). */
const APP_API_KEY: string = process.env.EXPO_PUBLIC_APP_API_KEY || "";

// ---------------------------------------------------------------------------
// §Calendar shapes (mirror the controller's local Pydantic `CalendarEntryModel`)
// ---------------------------------------------------------------------------

/**
 * One calendar entry — the safe, render-only projection of a scheduled publish
 * returned by `GET /me/calendar` and `PATCH /me/calendar/{id}`. Exactly these
 * five fields (never `user_id` / `result` / `error` / `attempts`). `job_id` and
 * `scheduled_at` are nullable defensively; `status` is widened to `string` so a
 * new server-side status never breaks rendering.
 */
export interface CalendarEntry {
  /** Row id — the path param for PATCH /me/calendar/{id}. */
  id: string;
  /** The completed job whose final output publishes (nullable defensively). */
  job_id: string | null;
  /** Target platforms (subset of the schedulable platforms). */
  platforms: string[];
  /** ISO-8601 UTC time the reel will publish / published at. */
  scheduled_at: string | null;
  /** Lifecycle status; widened to `string` for forward-compatibility. */
  status: string;
}

// ---------------------------------------------------------------------------
// Request helper (unwraps the { status, data, message } envelope) — a scoped
// copy of the shared `lib/api.ts` client so this module stays disjoint from it.
// ---------------------------------------------------------------------------

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

async function calendarRequest<T>(
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
    });
  } catch (err) {
    // Network-level failure (DNS, offline, aborted).
    if (isAbortError(err)) throw err;
    throw new ApiError(
      `Network error contacting the API: ${
        err instanceof Error ? err.message : String(err)
      }`,
      0,
      err,
    );
  }

  // Parse the envelope defensively — error responses may not be JSON.
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
      envelope?.message || `Request failed with status ${res.status}`.trim();
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
// Defensive normalisation
// ---------------------------------------------------------------------------

/** Coerce an unknown row into a well-formed {@link CalendarEntry}, or `null`. */
function normalizeEntry(value: unknown): CalendarEntry | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const id = typeof row.id === "string" ? row.id : "";
  if (!id) return null;
  const platforms = Array.isArray(row.platforms)
    ? row.platforms.filter((p): p is string => typeof p === "string")
    : [];
  return {
    id,
    job_id: typeof row.job_id === "string" ? row.job_id : null,
    platforms,
    scheduled_at:
      typeof row.scheduled_at === "string" ? row.scheduled_at : null,
    status: typeof row.status === "string" ? row.status : "pending",
  };
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

/**
 * GET /me/calendar?start=&end= — the caller's scheduled + already-published
 * reels whose `scheduled_at` falls in the `[start, end]` UTC window (both
 * ISO-8601). Strictly owner-scoped server-side. The backend clamps an over-wide
 * window to at most ~92 days and rejects an inverted / empty / unparseable range
 * with a `400` ({@link ApiError}). The payload is normalized defensively so a
 * partial/legacy row degrades instead of throwing; junk rows are dropped.
 */
export async function fetchCalendar(
  startISO: string,
  endISO: string,
  options?: RequestOptions,
): Promise<CalendarEntry[]> {
  const qs = `?start=${encodeURIComponent(startISO)}&end=${encodeURIComponent(
    endISO,
  )}`;
  const data = await calendarRequest<
    CalendarEntry[] | { data?: CalendarEntry[] }
  >(`/me/calendar${qs}`, { options });
  const rows = Array.isArray(data) ? data : (data?.data ?? []);
  return rows
    .map(normalizeEntry)
    .filter((e): e is CalendarEntry => e !== null);
}

/**
 * PATCH /me/calendar/{id} — move a still-`pending` schedule owned by the caller
 * to a new future UTC time. `scheduledAtISO` must be an ISO-8601 UTC timestamp in
 * the future. The backend yields `404` for an unknown/foreign id, `409` when the
 * schedule is no longer pending (publishing / published / failed / canceled, or
 * claimed by the due-runner mid-request), and `400` for a missing / unparseable /
 * past time — each surfaced as an {@link ApiError}. Returns the moved entry.
 */
export async function reschedulePublish(
  scheduleId: string,
  scheduledAtISO: string,
  options?: RequestOptions,
): Promise<CalendarEntry> {
  const data = await calendarRequest<CalendarEntry>(
    `/me/calendar/${encodeURIComponent(scheduleId)}`,
    { method: "PATCH", body: { scheduled_at: scheduledAtISO }, options },
  );
  const entry = normalizeEntry(data);
  if (entry === null) {
    throw new ApiError(
      "Malformed response: expected a calendar entry from the API.",
      200,
      data,
    );
  }
  return entry;
}
