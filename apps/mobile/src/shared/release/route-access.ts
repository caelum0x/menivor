/**
 * Who may open a screen. Pure, so the decision is unit-tested; RouteGate turns
 * it into a redirect before the screen component ever mounts.
 *
 * - "internal": not on the release surface and the lab flag is off. Nobody
 *   reaches it (labs, admin, developer keys, Mint token transfers, ...).
 * - "signin": a creator screen, but there is no signed-in account. Menivor is
 *   signup-first; there is no guest use.
 * - "wait": the stored session is still loading.
 * - "allow": render the screen.
 */

import { isLabEnabled } from "./build-flags";
import { isRouteAvailable, normalizeRoute } from "./surface";

/** Screens that work without an account: sign-in, legal, help, share links. */
export const PUBLIC_ROUTES = [
  "/",
  "/waitlist",
  "/beta-request",
  "/privacy",
  "/support",
  "/legal/terms",
  "/legal/privacy",
  "/legal/creator-contract",
  "/r/[token]",
] as const;

export type RouteDecision = "allow" | "internal" | "signin" | "wait";

export interface RouteAccessContext {
  lab?: boolean;
  signedIn: boolean;
  authLoading: boolean;
}

function matchesPattern(pattern: string, path: string): boolean {
  const want = pattern.split("/").filter(Boolean);
  const got = path.split("/").filter(Boolean);
  if (want.length !== got.length) return false;
  return want.every((part, index) => {
    if (part.startsWith("[") && part.endsWith("]")) return (got[index] ?? "").length > 0;
    return part === got[index];
  });
}

/** True when a screen is usable without signing in. */
export function isPublicRoute(path: string): boolean {
  const normalized = normalizeRoute(path);
  return PUBLIC_ROUTES.some((pattern) => matchesPattern(pattern, normalized));
}

/**
 * Decide access for an expo-router route name (`"job/[id]"`, `"wallet/index"`,
 * `"(tabs)"`) or a pathname.
 */
export function routeAccess(
  routeName: string,
  { lab = isLabEnabled(), signedIn, authLoading }: RouteAccessContext,
): RouteDecision {
  const path = normalizeRoute(routeName.startsWith("/") ? routeName : `/${routeName}`);
  if (!isRouteAvailable(path, lab)) return "internal";
  if (isPublicRoute(path)) return "allow";
  if (authLoading) return "wait";
  return signedIn ? "allow" : "signin";
}
