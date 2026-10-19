/**
 * Data-driven contextual deep-links.
 *
 * The app's advanced surfaces (Studio, Insights, Wallet, Marketplace, …) are
 * otherwise only reachable through the flat registry menu on the Me tab. This
 * map lets a funnel screen surface the two or three deep screens a creator
 * most often needs NEXT from where they are, turning dead-end funnels into
 * discoverable entry points.
 *
 * Each context maps to an ordered list of registry routes. `getContextualLinks`
 * resolves them against the live registry, silently dropping any route that is
 * unregistered or hidden — so a context can never render a broken link.
 */

import { getScreen, type ScreenMeta } from "./registry";
import { isRouteAvailable } from "@/src/shared/release/surface";

/** The known funnel contexts that can host contextual deep-links. */
export type NavContext =
  | "create"
  | "jobs"
  | "broll"
  | "compose"
  | "publish"
  | "wallet";

/** Ordered registry routes to surface for each funnel context. */
const CONTEXTUAL_ROUTES: Record<NavContext, readonly string[]> = {
  // From the reel creator: the studios that shape the reel + the render/media hubs.
  create: [
    "/studio/captions",
    "/studio/scripts",
    "/studio/templates",
    "/media-gateway",
    "/render",
  ],
  // From the jobs library: where a finished reel goes next.
  jobs: [
    "/jobs/reels/tasks",
    "/editor",
    "/scheduled",
    "/analytics",
    "/performance",
  ],
  // From the B-roll studio: the motion/media surfaces that feed it.
  broll: ["/media-gateway", "/studio/motion", "/catalog", "/diffusion-lab"],
  // From reel compose: templates + caption studio.
  compose: ["/studio/templates", "/studio/captions", "/marketplace"],
  // From publishing: scheduling, calendar, connections.
  publish: ["/scheduled", "/calendar", "/connections/manage", "/trends-feed"],
  // From the wallet: where credit is spent + earned.
  wallet: ["/spend", "/wallet/plans", "/clipmarket", "/marketplace"],
};

/**
 * Resolve a context's routes into registered screen metadata, in declared
 * order. Unregistered, hidden or staff-only routes are dropped.
 */
export function getContextualLinks(context: NavContext): readonly ScreenMeta[] {
  const routes = CONTEXTUAL_ROUTES[context] ?? [];
  const out: ScreenMeta[] = [];
  for (const route of routes) {
    const meta = getScreen(route);
    if (meta && !meta.hidden && meta.audience !== "staff" && isRouteAvailable(meta.route)) out.push(meta);
  }
  return out;
}
