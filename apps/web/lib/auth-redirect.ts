/**
 * Post-auth redirect helpers shared by server pages (sign-in, sign-up,
 * onboarding) and client CTAs. No "use client" directive: safe to call from
 * server components.
 */

/**
 * Only same-origin paths are accepted as post-auth destinations, so a crafted
 * `?redirect_url=https://evil.example` can never bounce a user off site.
 * Absolute URLs are accepted only when their host equals `allowedHost` (Clerk's
 * own middleware redirect passes the full request URL); they are reduced to
 * path + query. Returns `fallback` for anything else.
 */
export function safeRelativePath(
  raw: string | null | undefined,
  fallback: string,
  allowedHost?: string | null,
): string {
  let value = (raw ?? "").trim();
  if (allowedHost && /^https?:\/\//i.test(value)) {
    try {
      const url = new URL(value);
      if (url.host !== allowedHost) return fallback;
      value = `${url.pathname}${url.search}`;
    } catch {
      return fallback;
    }
  }
  if (!value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return fallback;
  }
  return value.slice(0, 512);
}

/** `/sign-up` URL that returns the new account to `returnTo` after onboarding. */
export function signUpHref(returnTo: string): string {
  return `/sign-up?redirect_url=${encodeURIComponent(returnTo)}`;
}

/** `/sign-in` URL that returns the user to `returnTo`. */
export function signInHref(returnTo: string): string {
  return `/sign-in?redirect_url=${encodeURIComponent(returnTo)}`;
}
