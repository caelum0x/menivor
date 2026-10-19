/**
 * Server-side principal resolution for Next route handlers that spend paid
 * upstream credits (e.g. the Winning Hook Finder's TypeSafe/Jev calls).
 *
 * A caller is authenticated when it presents the same credential the web app
 * already sends to the Menivor API: the browser's device-session key (every
 * visitor gets one, zero signup) or a signed-in account token, as `x-api-key`
 * or `Authorization: Bearer <token>`. The credential is verified by the API
 * itself (`GET {API_BASE}/me`, which runs `resolve_principal`), so the web tier
 * never re-implements key or JWT checks.
 *
 * Verified credentials are cached briefly per Worker isolate, keyed by a
 * SHA-256 of the credential (the raw secret is never kept), so a burst of
 * rankings costs one verification round-trip.
 */

import { API_BASE } from "@/src/shared/api/base";

export interface Principal {
  readonly userId: string;
}

export type PrincipalResult =
  | { readonly ok: true; readonly principal: Principal }
  | { readonly ok: false; readonly reason: "missing" | "invalid" | "unavailable" };

interface Credential {
  readonly header: "x-api-key" | "authorization";
  readonly value: string;
}

const MAX_CREDENTIAL_LENGTH = 4096;
const DEFAULT_TTL_MS = 5 * 60 * 1000;
const DEFAULT_MAX_KEYS = 5_000;
const VERIFY_TIMEOUT_MS = 8_000;

/** The caller's credential from `x-api-key` or a Bearer header, else null. */
export function extractCredential(request: Request): Credential | null {
  const apiKey = request.headers.get("x-api-key")?.trim();
  if (apiKey && apiKey.length <= MAX_CREDENTIAL_LENGTH) {
    return { header: "x-api-key", value: apiKey };
  }
  const bearer = request.headers.get("authorization")?.match(/^Bearer\s+(.+)$/i)?.[1]?.trim();
  if (bearer && bearer.length <= MAX_CREDENTIAL_LENGTH) {
    return { header: "authorization", value: bearer };
  }
  return null;
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

function userIdFrom(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const data = (payload as { data?: unknown }).data;
  if (!data || typeof data !== "object") return null;
  const id = (data as { user_id?: unknown }).user_id;
  if (typeof id === "string" && id.trim()) return id.trim();
  if (typeof id === "number" && Number.isFinite(id)) return String(id);
  return null;
}

export interface PrincipalResolverOptions {
  readonly apiBase?: string;
  readonly fetchImpl?: typeof fetch;
  readonly ttlMs?: number;
  readonly maxKeys?: number;
  readonly now?: () => number;
}

export interface PrincipalResolver {
  resolve(request: Request): Promise<PrincipalResult>;
}

interface CacheEntry {
  readonly userId: string;
  readonly expiresAt: number;
}

export function createPrincipalResolver(options: PrincipalResolverOptions = {}): PrincipalResolver {
  const apiBase = (options.apiBase ?? API_BASE).replace(/\/+$/, "");
  const ttlMs = options.ttlMs ?? DEFAULT_TTL_MS;
  const maxKeys = options.maxKeys ?? DEFAULT_MAX_KEYS;
  const now = options.now ?? Date.now;
  const cache = new Map<string, CacheEntry>();

  function remember(key: string, userId: string): void {
    cache.delete(key);
    cache.set(key, { userId, expiresAt: now() + ttlMs });
    while (cache.size > maxKeys) {
      const oldest = cache.keys().next();
      if (oldest.done) return;
      cache.delete(oldest.value);
    }
  }

  async function verify(credential: Credential): Promise<PrincipalResult> {
    const fetchImpl = options.fetchImpl ?? fetch;
    const headers: Record<string, string> =
      credential.header === "x-api-key"
        ? { "x-api-key": credential.value }
        : { Authorization: `Bearer ${credential.value}` };
    let response: Response;
    try {
      response = await fetchImpl(`${apiBase}/me`, {
        method: "GET",
        headers,
        cache: "no-store",
        signal: AbortSignal.timeout(VERIFY_TIMEOUT_MS),
      });
    } catch {
      return { ok: false, reason: "unavailable" };
    }
    if (response.status === 401 || response.status === 403) {
      return { ok: false, reason: "invalid" };
    }
    if (!response.ok) return { ok: false, reason: "unavailable" };
    const userId = userIdFrom(await response.json().catch(() => null));
    if (!userId) return { ok: false, reason: "unavailable" };
    return { ok: true, principal: { userId } };
  }

  return {
    async resolve(request: Request): Promise<PrincipalResult> {
      const credential = extractCredential(request);
      if (!credential) return { ok: false, reason: "missing" };

      const key = await sha256Hex(`${credential.header}:${credential.value}`);
      const cached = cache.get(key);
      if (cached && cached.expiresAt > now()) {
        return { ok: true, principal: { userId: cached.userId } };
      }

      const result = await verify(credential);
      if (result.ok) remember(key, result.principal.userId);
      else cache.delete(key);
      return result;
    },
  };
}
