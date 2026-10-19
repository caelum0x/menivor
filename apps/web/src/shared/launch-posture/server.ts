import { WAITLIST_MODE } from "@/lib/clerk";
import { API_BASE } from "@/src/shared/api/base";
import { resolveLaunchPosture, WAITLIST_POSTURE, type LaunchPosture } from "./posture";

/** How long a read of /launch/status is reused, in seconds. */
export const LAUNCH_STATUS_REVALIDATE_S = 60;
const FETCH_TIMEOUT_MS = 2500;
/** A last-known-good read survives a brief API outage for this long. */
const STALE_GRACE_MS = 10 * 60 * 1000;

interface CacheEntry {
  readonly posture: LaunchPosture;
  readonly expiresAt: number;
}

// Per-isolate memo: the Worker's data cache is a no-op, so this is what keeps
// the landing page from hitting the API on every request.
let cached: CacheEntry | null = null;

async function readStatus(): Promise<unknown> {
  const response = await fetch(`${API_BASE}/launch/status`, {
    headers: { accept: "application/json" },
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    next: { revalidate: LAUNCH_STATUS_REVALIDATE_S },
  });
  if (!response.ok) throw new Error(`launch status ${response.status}`);
  return response.json();
}

/**
 * Server-side launch posture for marketing CTAs. WAITLIST_MODE wins; an
 * unreachable or malformed status reuses a recent good read if there is one,
 * otherwise falls back to the waitlist posture (retried on the next request).
 */
export async function getLaunchPosture(): Promise<LaunchPosture> {
  if (WAITLIST_MODE) return WAITLIST_POSTURE;
  const now = Date.now();
  if (cached && cached.expiresAt > now) return cached.posture;
  try {
    const raw = await readStatus();
    const posture = resolveLaunchPosture(raw, false);
    if (posture !== WAITLIST_POSTURE) {
      cached = { posture, expiresAt: now + LAUNCH_STATUS_REVALIDATE_S * 1000 };
    }
    return posture;
  } catch (err) {
    if (cached && cached.expiresAt + STALE_GRACE_MS > now) return cached.posture;
    console.warn(
      JSON.stringify({ event: "launch_status_unavailable", error: String(err).slice(0, 200) }),
    );
    return WAITLIST_POSTURE;
  }
}
