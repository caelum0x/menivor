/**
 * Detects Clerk's browser-side "clerk-js failed to load" failure so the app
 * can show an actionable fallback instead of leaving a dead sign-in/sign-up
 * surface with zero feedback.
 *
 * Clerk throws this (code `failed_to_load_clerk_js`) as an uncaught error or
 * unhandled promise rejection when its CDN script is blocked, slow or 404s —
 * ad blockers, aggressive DNS/firewall filters and flaky mobile networks all
 * trigger it. Confirmed in production: GlitchTip issue #926
 * (errors.ereboslab.com/3), a real visitor on https://menivor.com/ whose
 * sign-in surface broke silently with nothing shown to them.
 */
export function isClerkLoadFailure(message: string | undefined | null): boolean {
  if (!message) return false;
  return /failed_to_load_clerk_js/i.test(message);
}
