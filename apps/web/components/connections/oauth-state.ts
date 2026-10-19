/**
 * Client-only bridge that remembers which provider an in-flight OAuth connect
 * belongs to across the full-page redirect to the provider and back. The opaque,
 * single-use CSRF `state` returned by GET /connections/{provider}/authorize is
 * used as the key, so the callback can recover the provider even if the redirect
 * URL doesn't echo it. Nothing sensitive is stored — only the provider slug — and
 * every entry is consumed exactly once. All access is guarded so a disabled /
 * throwing `sessionStorage` (private mode) degrades to a no-op instead of
 * breaking the connect flow.
 */

import type { SocialProvider } from "@/lib/types";

const KEY_PREFIX = "reelforge.oauth.provider:";

/** Remember the provider for a pending connect, keyed by its CSRF `state`. */
export function rememberPendingProvider(
  state: string,
  provider: SocialProvider,
): void {
  if (!state) return;
  try {
    window.sessionStorage.setItem(`${KEY_PREFIX}${state}`, String(provider));
  } catch {
    // sessionStorage unavailable (private mode / disabled) — connect still works
    // when the callback carries an explicit `provider` query param.
  }
}

/**
 * Recover and consume the provider stored for `state`. Returns `null` when no
 * entry exists (unknown / already-consumed / storage unavailable).
 */
export function takePendingProvider(state: string): string | null {
  if (!state) return null;
  try {
    const key = `${KEY_PREFIX}${state}`;
    const provider = window.sessionStorage.getItem(key);
    if (provider !== null) window.sessionStorage.removeItem(key);
    return provider;
  } catch {
    return null;
  }
}
