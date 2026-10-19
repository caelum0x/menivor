/**
 * listmonk-subscribe.ts — tiny, dependency-free, SERVER-SIDE subscribe client.
 *
 * Canonical copy: infra-box/stacks/listmonk/client/listmonk-subscribe.ts.
 * Copied verbatim into each site's backend (keep copies in sync by hand):
 *   - videogen/apps/web/lib/listmonk.ts              (Menivor)
 *   - yok-content-engine/apps/web/src/lib/listmonk.ts (yokharita)
 *   - scribase/apps/www/lib/listmonk.ts               (Scribase)
 *
 * It calls listmonk's PUBLIC subscription API
 *   POST {LISTMONK_URL}/api/public/subscription  { email, name, list_uuids }
 * which needs no credentials: the list must be type "public" and the
 * listmonk setting "Enable public subscription page" must be on (bootstrap.py
 * does both). With a double-opt-in list, listmonk emails a confirmation link and
 * the address only receives mail after it is clicked.
 *
 * No admin user or API token is ever read or sent here, so nothing a browser
 * can reach can leak one. Browsers talk to the site's own route handler, which
 * calls this module.
 *
 * Runtime: any fetch + AbortSignal.timeout runtime (Node 18+, Cloudflare Workers).
 */

export interface ListmonkConfig {
  /** Base URL of the listmonk instance, no trailing slash. */
  readonly url: string;
  /** One or more public list UUIDs to subscribe to. */
  readonly listUuids: readonly string[];
}

export type SubscribeResult =
  /** Accepted. `needsConfirmation` = a double-opt-in email was sent. */
  | { readonly ok: true; readonly needsConfirmation: boolean }
  /** listmonk rejected the input (bad address, blocklisted domain...). */
  | { readonly ok: false; readonly reason: "rejected"; readonly detail: string }
  /** Not configured, unreachable, timed out, or a 5xx. */
  | { readonly ok: false; readonly reason: "unavailable"; readonly detail: string };

export const LISTMONK_TIMEOUT_MS = 8000;
const MAX_EMAIL_LENGTH = 254;
const MAX_NAME_LENGTH = 100;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type EnvLike = Readonly<Record<string, string | undefined>>;

/**
 * Read LISTMONK_URL + LISTMONK_LIST_UUID (comma-separated allowed) from env.
 * Returns null when either is missing or malformed, so callers can answer with
 * a clear "signups are not enabled yet" instead of failing.
 */
export function readListmonkConfig(env: EnvLike): ListmonkConfig | null {
  const url = (env.LISTMONK_URL ?? "").trim().replace(/\/+$/, "");
  const listUuids = (env.LISTMONK_LIST_UUID ?? "")
    .split(",")
    .map((value) => value.trim())
    .filter((value) => value.length > 0);
  if (!/^https?:\/\/[^\s/]+/i.test(url)) return null;
  if (listUuids.length === 0 || !listUuids.every((id) => UUID_PATTERN.test(id))) return null;
  return { url, listUuids };
}

/** Normalize + validate an email. Returns null when it is not plausible. */
export function normalizeEmail(input: unknown): string | null {
  if (typeof input !== "string") return null;
  const email = input.trim().toLowerCase();
  if (email.length === 0 || email.length > MAX_EMAIL_LENGTH) return null;
  return EMAIL_PATTERN.test(email) ? email : null;
}

function readErrorDetail(body: unknown): string {
  if (typeof body === "object" && body !== null && "message" in body) {
    return String((body as { message: unknown }).message).slice(0, 200);
  }
  return "";
}

/**
 * Subscribe one address. Never throws: every failure maps to a SubscribeResult.
 * `fetchImpl` is injectable for tests.
 */
export async function subscribeToListmonk(
  config: ListmonkConfig,
  input: { readonly email: string; readonly name?: string },
  fetchImpl: typeof fetch = fetch,
): Promise<SubscribeResult> {
  const email = normalizeEmail(input.email);
  if (!email) return { ok: false, reason: "rejected", detail: "invalid email" };
  const name = (input.name ?? "").trim().slice(0, MAX_NAME_LENGTH);

  let response: Response;
  try {
    response = await fetchImpl(`${config.url}/api/public/subscription`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ email, name, list_uuids: config.listUuids }),
      signal: AbortSignal.timeout(LISTMONK_TIMEOUT_MS),
    });
  } catch (error) {
    const detail = error instanceof Error ? error.name : "network error";
    return { ok: false, reason: "unavailable", detail };
  }

  const body: unknown = await response.json().catch(() => null);
  if (response.ok) {
    const data =
      typeof body === "object" && body !== null && "data" in body
        ? (body as { data: unknown }).data
        : null;
    const needsConfirmation =
      typeof data === "object" && data !== null && "has_optin" in data
        ? (data as { has_optin: unknown }).has_optin === true
        : false;
    return { ok: true, needsConfirmation };
  }
  // 400 = listmonk validation (bad email, private list, public page disabled).
  if (response.status === 400) {
    return { ok: false, reason: "rejected", detail: readErrorDetail(body) };
  }
  return { ok: false, reason: "unavailable", detail: `HTTP ${response.status}` };
}
