/**
 * The release surface: the screens a store build of Menivor exposes.
 *
 * Menivor ships as a focused AI video maker: create a reel from a prompt or a
 * link, edit it, caption it, voice it and export it. Everything else in app/
 * (calculators, admin consoles, developer/API tooling, token transfers, team
 * administration, marketplaces) stays in the codebase for the web console and
 * internal use, but is reachable only in a dev session started with
 * `EXPO_PUBLIC_ENABLE_LAB=1` (see build-flags.isLabEnabled). The root layout's
 * RouteGate renders a redirect instead of any other screen, and menus filter
 * their rows through {@link isRouteAvailable}.
 */

import { isLabEnabled } from "./build-flags";

/** Expo-router route patterns (route groups stripped, `[param]` = one segment). */
export const RELEASE_ROUTES = [
  // Sign-in and the four tabs
  "/",
  "/create",
  "/jobs",
  "/broll",
  "/me",
  // Me tab "Tools" groups (lists only release screens from the registry)
  "/navigation/discoverability/[group]",
  // Signup closed for a launch phase: early access and waitlist
  "/beta-request",
  "/waitlist",
  // Create: prompt or link -> variants -> render
  "/create/advanced",
  "/create/results",
  "/ideas",
  "/ad-studio",
  "/ad-studio/[id]",
  "/repurpose/clipping",
  "/repurpose/clipping/ingest",
  "/repurpose/clipping/[id]",
  "/repurpose/clipping/clip/[id]",
  "/film",
  "/compose",
  "/characters",
  "/drafts",
  // Footage in
  "/capture",
  "/capture/screen-import",
  "/capture/trim",
  "/uploads",
  // Renders
  "/job/[id]",
  "/reels",
  "/reels/[id]",
  "/reels/render-job",
  "/jobs/reels/tasks",
  "/jobs/reels/tasks/[id]",
  "/jobs/reels/batch/[batchId]",
  "/r/[token]",
  // Edit, captions, voice, look
  "/editor",
  "/studio/captions",
  "/studio/captions/hook-score",
  "/studio/captions/hormozi",
  "/studio/captions/safezones",
  "/studio/captions/loop-check",
  "/studio/captions/beat-fit",
  "/studio/captions/seo",
  "/studio/dub",
  "/studio/scripts",
  "/studio/scripts/generate",
  "/studio/scripts/[id]",
  "/studio/templates",
  "/studio/template/[slug]",
  "/studio/preset",
  "/studio/preset/[id]",
  "/templates",
  "/studio/design",
  "/studio/design/[id]",
  "/studio/voices",
  "/studio/my-voices",
  "/voices",
  "/account/voices",
  "/account/voices/[id]",
  "/avatars",
  "/studio/avatars",
  "/studio/avatar/[id]",
  "/account/avatars",
  "/account/avatars/[id]",
  "/brand",
  "/catalog/caption-styles",
  "/catalog/music",
  "/catalog/layouts",
  "/catalog/templates",
  "/catalog/backgrounds",
  "/catalog/cover-styles",
  "/catalog/dub-languages",
  "/catalog/hooks",
  "/catalog/presets",
  // Credits and Pro (store-priced on iOS/Android)
  "/wallet",
  "/wallet/top-up",
  "/wallet-topup",
  "/wallet/plans",
  "/plan",
  "/wallet/history",
  "/wallet/billing-history",
  // Account
  "/notifications",
  "/account/settings",
  "/privacy",
  "/account/privacy",
  "/support",
  "/legal/terms",
  "/legal/privacy",
  "/legal/creator-contract",
] as const;

/**
 * Static screens that sit next to a released `[param]` route and would match
 * it, but are not released themselves (expo-router resolves static first).
 */
export const SHADOWED_STATIC_ROUTES = ["/reels/schedule"] as const;

const RELEASE_PATTERNS: readonly string[][] = RELEASE_ROUTES.map(splitPath);

function splitPath(path: string): string[] {
  return path.split("/").filter((segment) => segment.length > 0);
}

/**
 * Normalise a pathname or href: drop query/hash, `(group)` segments, a
 * trailing `/index` and trailing slashes.
 */
export function normalizeRoute(path: string): string {
  const bare = path.split(/[?#]/, 1)[0] ?? "";
  const segments = splitPath(bare).filter(
    (segment) => !(segment.startsWith("(") && segment.endsWith(")")),
  );
  if (segments[segments.length - 1] === "index") segments.pop();
  return `/${segments.join("/")}`;
}

function matches(pattern: readonly string[], segments: readonly string[]): boolean {
  if (pattern.length !== segments.length) return false;
  return pattern.every((part, index) => {
    if (part.startsWith("[") && part.endsWith("]")) {
      return (segments[index] ?? "").length > 0;
    }
    return part === segments[index];
  });
}

/** True when a store build exposes this path. */
export function isReleaseRoute(path: string): boolean {
  const normalized = normalizeRoute(path);
  if ((SHADOWED_STATIC_ROUTES as readonly string[]).includes(normalized)) return false;
  const segments = splitPath(normalized);
  return RELEASE_PATTERNS.some((pattern) => matches(pattern, segments));
}

/** Lab sessions can open every screen; every other build only the release surface. */
export function isRouteAvailable(path: string, lab: boolean = isLabEnabled()): boolean {
  return lab || isReleaseRoute(path);
}
