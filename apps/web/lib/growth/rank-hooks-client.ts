/**
 * Browser client for the Winning Hook Finder route.
 *
 * Calls the same-origin Next route `POST /api/v1/growth/rank-hooks` (NOT the
 * external ReelForge backend — the Jev key stays server-side there). Returns a
 * typed {@link RankHooksResponse} or throws {@link RankHooksError} with a
 * user-facing message.
 */

import type { RankHooksResponse } from "./types";

const ENDPOINT = "/api/v1/growth/rank-hooks";

export class RankHooksError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "RankHooksError";
    this.status = status;
  }
}

/** Split a textarea blob into trimmed, non-empty hook lines. */
export function splitHookLines(raw: string): string[] {
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/** POST the hook variants and return the ranked result. */
export async function rankHooks(
  hooks: readonly string[],
  signal?: AbortSignal,
): Promise<RankHooksResponse> {
  let res: Response;
  try {
    res = await fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hooks }),
      signal,
    });
  } catch (error) {
    throw new RankHooksError(
      error instanceof Error && error.name === "AbortError"
        ? "Request cancelled."
        : "Could not reach the ranking service. Check your connection and try again.",
      0,
    );
  }

  let payload: unknown = null;
  try {
    payload = await res.json();
  } catch {
    // Non-JSON body — fall through to status-based error below.
  }

  if (!res.ok) {
    const message =
      payload && typeof payload === "object" && typeof (payload as { error?: unknown }).error === "string"
        ? (payload as { error: string }).error
        : `Ranking failed (HTTP ${res.status}).`;
    throw new RankHooksError(message, res.status);
  }

  return payload as RankHooksResponse;
}
