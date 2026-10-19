/**
 * Clerk configuration detection.
 *
 * The public marketing site (`/`, `/(marketing)/*`, `/pricing`) must render
 * cleanly even when no real Clerk instance is provisioned. A Clerk publishable
 * key encodes its Frontend API domain (base64, `$`-terminated) — a PLACEHOLDER
 * key such as `pk_test_Y2xlcmsuZXhhbXBsZS5jb20k` decodes to `clerk.example.com`,
 * and mounting `<ClerkProvider>` with it makes the browser try to load
 * `https://clerk.example.com/...`, which DNS-fails and breaks the page.
 *
 * `hasRealClerkKey` lets us mount Clerk (provider + `SignedIn`/`SignedOut`/
 * `UserButton`) ONLY when a genuine key is present, and otherwise render the
 * logged-out marketing experience with no client-side Clerk script at all.
 *
 * `NEXT_PUBLIC_*` is inlined at build time, so this evaluates to a constant the
 * bundler can tree-shake — the placeholder branch ships zero Clerk runtime.
 */
export const clerkPublishableKey =
  process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ?? "";

function decodeClerkFapiDomain(publishableKey: string): string {
  const match = publishableKey.match(/^pk_(?:test|live)_(.+)$/);
  const body = match?.[1];
  if (!body) return "";
  try {
    // Key body is base64 of "<fapi-domain>$".
    const decoded =
      typeof atob === "function"
        ? atob(body)
        : Buffer.from(body, "base64").toString("utf-8");
    return decoded.replace(/\$+$/, "");
  } catch {
    return "";
  }
}

const fapiDomain = decodeClerkFapiDomain(clerkPublishableKey);

/**
 * True only for a real, non-placeholder Clerk publishable key. Placeholder
 * keys (empty, malformed, or pointing at an `*.example.com` Frontend API) are
 * treated as "not configured" so the public site never loads a dead Clerk SDK.
 */
export const hasRealClerkKey: boolean =
  clerkPublishableKey.startsWith("pk_") &&
  fapiDomain.length > 0 &&
  fapiDomain !== "clerk.example.com" &&
  !fapiDomain.endsWith(".example.com");

/**
 * Waitlist mode: an explicit fallback for when generation is offline — every
 * marketing CTA routes to the KV waitlist instead of implying a working
 * product.
 *
 * OFF by default: the visitor-operable free tier is REAL now. The API's
 * keyless `captions_only` render path is live (proven end-to-end against
 * api.menivor.com) and web visitors get a zero-signup device session with
 * free credits (`src/shared/device`), so `/create` works without Clerk or
 * checkout. Re-enable the waitlist posture with `NEXT_PUBLIC_WAITLIST_MODE=1`
 * if generation capacity has to be pulled. Build-time constant —
 * `NEXT_PUBLIC_*` is inlined, so the inactive branch is tree-shaken.
 */
export const WAITLIST_MODE: boolean =
  process.env.NEXT_PUBLIC_WAITLIST_MODE === "1";

/**
 * Clerk Frontend API proxy URL (e.g. `https://menivor.com/__clerk`).
 *
 * OFF by default (empty): Clerk talks to the FAPI domain encoded in the
 * publishable key (clerk.menivor.com). When set, ClerkProvider and
 * clerkMiddleware route all FAPI traffic through the app's own domain, where
 * middleware.ts forwards it to Clerk (lib/clerk-proxy.ts). Only an absolute
 * https URL is accepted; anything else is ignored so a typo can't break auth.
 * Must be set both at build time (.env.local, inlined) and in wrangler vars.
 * See README "Clerk Frontend API proxy".
 */
function normalizeProxyUrl(raw: string | undefined): string {
  const value = raw?.trim().replace(/\/+$/, "") ?? "";
  if (!value) return "";
  try {
    return new URL(value).protocol === "https:" ? value : "";
  } catch {
    return "";
  }
}

export const clerkProxyUrl: string = normalizeProxyUrl(
  process.env.NEXT_PUBLIC_CLERK_PROXY_URL,
);
