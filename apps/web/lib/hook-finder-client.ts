/**
 * Authenticated browser client for the Winning Hook Finder.
 *
 * `POST /api/v1/growth/rank-hooks` requires a verified caller (it spends
 * TypeSafe/Jev credits). This sends the signed-in session token (or a legacy
 * device-session key) as `x-api-key`, the same credential every other Menivor
 * web feature uses (see `src/shared/api/client.ts`). A 401 on a stored device
 * key re-exchanges the install id once (same account, fresh key) and retries.
 */

import { getStoredDeviceApiKey, refreshDeviceSession } from "@/src/shared/device/session";
import { getSessionToken } from "@/src/shared/api/session-token";
import { RankHooksError } from "@/lib/growth/rank-hooks-client";
import type { RankHooksResponse } from "@/lib/growth/types";

const ENDPOINT = "/api/v1/growth/rank-hooks";

/** The signed-in session token, else a legacy device key this browser holds. */
async function deviceKey(): Promise<string> {
  const session = await getSessionToken();
  if (session) return session;
  const stored = getStoredDeviceApiKey();
  if (stored) return stored;
  throw new RankHooksError("Sign in to rank hooks. It takes one click with Google or Apple.", 401);
}

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === "object") {
    const error = (payload as { error?: unknown }).error;
    if (typeof error === "string" && error) return error;
  }
  return `Ranking failed (HTTP ${status}).`;
}

/** POST the hook variants with the caller's credential and return the ranking. */
export async function rankHooksAuthenticated(
  hooks: readonly string[],
  signal?: AbortSignal,
): Promise<RankHooksResponse> {
  const body = JSON.stringify({ hooks });
  const send = (key: string): Promise<Response> =>
    fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-api-key": key },
      body,
      signal,
    });

  let res: Response;
  try {
    res = await send(await deviceKey());
    if (res.status === 401) {
      try {
        res = await send((await refreshDeviceSession()).api_key);
      } catch {
        // Keep the original 401 so the user sees the route's message.
      }
    }
  } catch (error) {
    if (error instanceof RankHooksError) throw error;
    throw new RankHooksError(
      error instanceof Error && error.name === "AbortError"
        ? "Request cancelled."
        : "Could not reach the ranking service. Check your connection and try again.",
      0,
    );
  }

  const payload: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new RankHooksError(errorMessage(payload, res.status), res.status);
  return payload as RankHooksResponse;
}
