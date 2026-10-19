/**
 * Menivor -> Rally bridge: "Find buyers for this product" deep link into Rally
 * onboarding with the product site prefilled.
 *
 * There is no default host: Rally's old host is shut down, so the
 * link only shows when RALLY_WEB_URL names a live Rally origin.
 */

/** Normalize the configured Rally origin (RALLY_WEB_URL); null when unset or invalid. */
export function rallyWebUrl(raw: string | undefined | null): string | null {
  const value = (raw ?? "").trim();
  if (!value) return null;
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return null;
    return parsed.origin;
  } catch {
    return null;
  }
}

/** `<rally>/rally/onboard?url=<product site>&source=menivor` (url omitted when unknown). */
export function rallyOnboardUrl(baseUrl: string, productUrl: string | null | undefined): string {
  const target = new URL("/rally/onboard", baseUrl);
  const site = (productUrl ?? "").trim();
  if (/^https?:\/\//i.test(site)) target.searchParams.set("url", site);
  target.searchParams.set("source", "menivor");
  return target.toString();
}
