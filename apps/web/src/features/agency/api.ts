/**
 * Agency portal — resell ReelForge generation to clients under your own keys.
 * Built on the real gateway provisioning-key + quote surface; the agency layer
 * adds per-client keys, a margin model, and revenue math (all pure).
 */

export {
  listKeys,
  createKey,
  quoteKey,
  type ProvisioningKey,
  type CreateKeyBody,
  type Quote,
} from "@/src/features/gateway/api";

/** basis points → percent string (250 → "2.5%"). */
export function bpsToPercent(bps: number): string {
  return `${((bps || 0) / 100).toFixed(2).replace(/\.00$/, "")}%`;
}

/** Integer microdollars → "$1.23". */
export function formatUsdMicros(micros: number): string {
  const usd = (micros || 0) / 1_000_000;
  const digits = usd !== 0 && Math.abs(usd) < 0.1 ? 3 : 2;
  return `$${usd.toFixed(digits)}`;
}

export interface MarginBreakdown {
  base_micros: number;
  markup_micros: number;
  min_fee_applied: boolean;
  customer_micros: number;
  margin_micros: number;
  margin_pct: number;
}

/**
 * Pure margin math mirroring the server's markup policy: customer pays
 * `base + max(base·markup_bps, min_fee)`; margin is what the agency keeps.
 */
export function computeMargin(
  baseMicros: number,
  markupBps: number,
  minFeeMicros: number,
): MarginBreakdown {
  const base = Math.max(0, Math.round(baseMicros));
  const rawMarkup = Math.round((base * Math.max(0, markupBps)) / 10_000);
  const markup = Math.max(rawMarkup, Math.max(0, minFeeMicros));
  const customer = base + markup;
  return {
    base_micros: base,
    markup_micros: markup,
    min_fee_applied: markup > rawMarkup,
    customer_micros: customer,
    margin_micros: markup,
    margin_pct: base > 0 ? Math.round((markup / base) * 10000) / 100 : 0,
  };
}
