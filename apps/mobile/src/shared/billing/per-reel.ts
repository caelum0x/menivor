/**
 * Per-reel price clarity for credit packs: what one finished reel costs on a
 * pack (pack price / credits, since one credit makes one reel), plus the
 * never-expire note shown next to every pack.
 *
 * Pure and unit-tested. Store packs pass the store's own local price and
 * currency (App Store / Play); hosted packs pass their USD list price.
 */

/** One credit makes one finished reel. */
export const CREDITS_PER_REEL = 1;

/** Shown beside every pack: the Creator Contract's pricing promises. */
export const PACK_TRUST_NOTE =
  "Credits never expire, and a failed render refunds its credit automatically.";

export interface PerReelInput {
  /** Pack price in major units (e.g. 9.99). */
  readonly price: number;
  /** Credits the pack grants. */
  readonly credits: number;
  /** ISO 4217 code of `price`. */
  readonly currencyCode: string;
}

/** Reels a pack makes (whole reels only). */
export function reelsInPack(credits: number): number {
  if (!Number.isFinite(credits) || credits <= 0) return 0;
  return Math.floor(credits / CREDITS_PER_REEL);
}

/** Price of one reel in major units, or null when it cannot be computed. */
export function perReelAmount(input: PerReelInput): number | null {
  const reels = reelsInPack(input.credits);
  if (reels === 0 || !Number.isFinite(input.price) || input.price < 0) return null;
  return input.price / reels;
}

function fractionDigitsFor(amount: number): number {
  // Keep sub-unit prices readable (0.39, 0.083) without long tails.
  if (amount === 0) return 0;
  if (amount < 0.1) return 3;
  return 2;
}

/** Format an amount in a currency, falling back to "<amount> <code>". */
export function formatMoney(amount: number, currencyCode: string, locale = "en-US"): string {
  const code = (currencyCode || "").trim().toUpperCase();
  const digits = fractionDigitsFor(amount);
  try {
    if (!/^[A-Z]{3}$/.test(code)) throw new Error("invalid currency");
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency: code,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(amount);
  } catch {
    return `${amount.toFixed(digits)}${code ? ` ${code}` : ""}`;
  }
}

/** "$0.39 per reel", "Free", or "" when the price is unknown. */
export function perReelLabel(input: PerReelInput, locale = "en-US"): string {
  const amount = perReelAmount(input);
  if (amount === null) return "";
  if (amount === 0) return "Free";
  return `${formatMoney(amount, input.currencyCode, locale)} per reel`;
}

/** "25 reels" / "1 reel" for a pack's credit count. */
export function reelsLabel(credits: number): string {
  const reels = reelsInPack(credits);
  return `${reels} reel${reels === 1 ? "" : "s"}`;
}

/**
 * Index of the pack with the lowest per-reel price, or -1 when fewer than two
 * packs are comparable (a single pack is not a "best value").
 */
export function lowestPerReelIndex(packs: readonly PerReelInput[]): number {
  let best = -1;
  let bestAmount = Number.POSITIVE_INFINITY;
  let comparable = 0;
  const currencies = new Set(packs.map((pack) => pack.currencyCode.toUpperCase()));
  if (currencies.size > 1) return -1;
  packs.forEach((pack, index) => {
    const amount = perReelAmount(pack);
    if (amount === null || amount === 0) return;
    comparable += 1;
    if (amount < bestAmount) {
      bestAmount = amount;
      best = index;
    }
  });
  return comparable >= 2 ? best : -1;
}
