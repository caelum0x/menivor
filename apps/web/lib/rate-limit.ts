/**
 * Small per-key token bucket for public, unauthenticated routes.
 *
 * State lives in module memory, so on Cloudflare Workers it is PER ISOLATE:
 * a determined abuser spread across isolates/colos gets more than `capacity`.
 * It stops casual scripted abuse; the durable limit belongs at the edge.
 * Recommended: add a Cloudflare WAF rate-limiting rule for the same path
 * (e.g. /api/newsletter, 5 requests / hour / IP, action: block).
 *
 * Keys are SHA-256 hashes of the client IP, so raw IPs are never kept in memory.
 */

export interface RateLimitOptions {
  /** Max requests allowed in a burst (bucket size). */
  readonly capacity: number;
  /** Window over which a full bucket refills, in milliseconds. */
  readonly refillMs: number;
  /** Upper bound on tracked keys; the oldest are evicted first. */
  readonly maxKeys?: number;
}

export type RateLimitDecision =
  | { readonly allowed: true; readonly remaining: number }
  | { readonly allowed: false; readonly retryAfterSeconds: number };

interface Bucket {
  readonly tokens: number;
  readonly updatedAt: number;
}

const DEFAULT_MAX_KEYS = 10_000;

export interface RateLimiter {
  check(key: string, now?: number): RateLimitDecision;
}

export function createRateLimiter(options: RateLimitOptions): RateLimiter {
  const { capacity, refillMs } = options;
  const maxKeys = options.maxKeys ?? DEFAULT_MAX_KEYS;
  const refillPerMs = capacity / refillMs;
  const buckets = new Map<string, Bucket>();

  function evictOverflow(): void {
    while (buckets.size > maxKeys) {
      const oldest = buckets.keys().next();
      if (oldest.done) return;
      buckets.delete(oldest.value);
    }
  }

  return {
    check(key: string, now: number = Date.now()): RateLimitDecision {
      const previous = buckets.get(key);
      const elapsed = previous ? Math.max(0, now - previous.updatedAt) : 0;
      const available = previous ? Math.min(capacity, previous.tokens + elapsed * refillPerMs) : capacity;

      // Re-insert so Map order tracks recency for eviction.
      buckets.delete(key);
      if (available < 1) {
        buckets.set(key, { tokens: available, updatedAt: now });
        return { allowed: false, retryAfterSeconds: Math.ceil((1 - available) / refillPerMs / 1000) };
      }
      buckets.set(key, { tokens: available - 1, updatedAt: now });
      evictOverflow();
      return { allowed: true, remaining: Math.floor(available - 1) };
    },
  };
}

/**
 * Best-effort client IP. `cf-connecting-ip` is set (and not spoofable) on
 * Cloudflare; the other headers cover local/proxied dev. `null` when unknown.
 */
export function clientIp(request: Request): string | null {
  const headers = request.headers;
  const direct = headers.get("cf-connecting-ip") ?? headers.get("x-real-ip");
  if (direct && direct.trim()) return direct.trim();
  const forwarded = headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return forwarded || null;
}

/** Hex SHA-256 of the IP, so the limiter never stores a raw address. */
export async function hashIp(ip: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(ip));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
