/**
 * OTT surface flags for the web build (Wave P P2). A surface shows only when the
 * master flag and its own flag are both on at build time, matching the API's
 * `OTT_ENABLED` plus per-surface flags (`app/domains/ott/flags.py`). All off by
 * default, so no OTT copy or link appears before its flag is Live.
 */

const ON = new Set(["1", "true", "yes", "on"]);

function on(raw: string | undefined): boolean {
  return ON.has((raw ?? "").trim().toLowerCase());
}

export function ottEnabled(raw: string | undefined = process.env.NEXT_PUBLIC_OTT_ENABLED): boolean {
  return on(raw);
}

/** Storefront pages (`/c/[handle]`) and the creator-profile channel link. */
export function ottStorefrontLive(
  master: string | undefined = process.env.NEXT_PUBLIC_OTT_ENABLED,
  surface: string | undefined = process.env.NEXT_PUBLIC_OTT_STOREFRONT_LIVE,
): boolean {
  return on(master) && on(surface);
}

/** The embed player (`/embed/[id]`). */
export function ottEmbedLive(
  master: string | undefined = process.env.NEXT_PUBLIC_OTT_ENABLED,
  surface: string | undefined = process.env.NEXT_PUBLIC_OTT_EMBED_LIVE,
): boolean {
  return on(master) && on(surface);
}

/** The creator studio (`/studio-ott`). */
export function ottCmsLive(
  master: string | undefined = process.env.NEXT_PUBLIC_OTT_ENABLED,
  surface: string | undefined = process.env.NEXT_PUBLIC_OTT_CMS_LIVE,
): boolean {
  return on(master) && on(surface);
}

/** Copy may say "protected streaming" only where access tier 1 is on (never "DRM"). */
export function ottAccessLive(
  master: string | undefined = process.env.NEXT_PUBLIC_OTT_ENABLED,
  surface: string | undefined = process.env.NEXT_PUBLIC_OTT_ACCESS_LIVE,
): boolean {
  return on(master) && on(surface);
}

/**
 * Wave P P3 surfaces (PM3.0 steward). Each reads the master flag plus its own
 * `NEXT_PUBLIC_OTT_<SURFACE>_LIVE`; all off by default. Next inlines only
 * literal `process.env.NEXT_PUBLIC_*` reads, so each flag is spelled out.
 */
export const P3_SURFACE_FLAGS = {
  viewers: () => process.env.NEXT_PUBLIC_OTT_VIEWERS_LIVE,
  plans: () => process.env.NEXT_PUBLIC_OTT_PLANS_LIVE,
  commerce: () => process.env.NEXT_PUBLIC_OTT_COMMERCE_LIVE,
  ads: () => process.env.NEXT_PUBLIC_OTT_ADS_LIVE,
  tv: () => process.env.NEXT_PUBLIC_OTT_TV_LIVE,
  live: () => process.env.NEXT_PUBLIC_OTT_LIVE_LIVE,
  chat: () => process.env.NEXT_PUBLIC_OTT_CHAT_LIVE,
  fast: () => process.env.NEXT_PUBLIC_OTT_FAST_LIVE,
  analytics: () => process.env.NEXT_PUBLIC_OTT_ANALYTICS_LIVE,
  ai: () => process.env.NEXT_PUBLIC_OTT_AI_LIVE,
  discovery: () => process.env.NEXT_PUBLIC_OTT_DISCOVERY_LIVE,
} as const;

export type OttP3Surface = keyof typeof P3_SURFACE_FLAGS;

/** Whether a P3 surface is live: the master flag and its own flag are both on. */
export function ottSurfaceLive(
  surface: OttP3Surface,
  master: string | undefined = process.env.NEXT_PUBLIC_OTT_ENABLED,
  own: string | undefined = P3_SURFACE_FLAGS[surface](),
): boolean {
  return on(master) && on(own);
}
