/**
 * Typed client for the one-time credit-pack API (`app/controllers/v1/credit_packs.py`).
 *
 * Contract (all responses use the `{status, data, message}` envelope that
 * `apiRequest` unwraps):
 *
 *   GET  /credit-packs[?currency=TRY]
 *        -> { packs: CreditPack[], charge_currency: "USD", checkout_open,
 *             display_rates: { TRY?: number } }
 *   POST /credit-packs/{id}/checkout  { channel: "web" }
 *        -> { checkout_url, provider: "creem", pack_id, credits, price_usd, ... }
 *           503 when card checkout is not configured on the server.
 *   POST /credit-packs/{id}/checkout  { channel: "store", transaction_id, product_id }
 *        -> { pack_id, credits_granted, already_redeemed, balance }
 *
 * The store rail used by `components/billing/StoreCreditPacks.tsx` talks to
 * the equivalent `/billing/store/credit-packs` routes through
 * `src/shared/billing/store-credits.ts`; both paths run the same server logic
 * (RevenueCat verification, one grant per store transaction).
 *
 * Credit amounts always come from the server. The TRY price is a display
 * estimate from a server-configured rate; the charge itself is in USD (web) or
 * the store's own local price (App Store / Play).
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type CreditPackChannel = "web" | "store";

export interface CreditPackDisplayPrice {
  currency: "TRY";
  amount: number;
  rate: number;
  approximate: true;
}

export interface CreditPack {
  id: string;
  label: string;
  credits: number;
  price_usd: number;
  charge_currency: "USD";
  store_product_id: string;
  web_checkout_available: boolean;
  store_purchase_available: boolean;
  /** Present only when `currency=TRY` was requested; null when no rate is set. */
  display_price?: CreditPackDisplayPrice | null;
}

export interface CreditPackCatalog {
  packs: CreditPack[];
  charge_currency: "USD";
  checkout_open: boolean;
  display_rates: { TRY?: number };
}

export interface CreditPackWebCheckout {
  provider: "creem";
  pack_id: string;
  credits: number;
  price_usd: number;
  charge_currency: "USD";
  checkout_url: string;
  reference: string;
}

export interface CreditPackRedemption {
  pack_id: string;
  credits_granted: number;
  already_redeemed: boolean;
  balance: number | null;
}

function isCreditPack(value: unknown): value is CreditPack {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.id === "string" &&
    row.id.length > 0 &&
    typeof row.credits === "number" &&
    Number.isFinite(row.credits) &&
    row.credits > 0 &&
    typeof row.price_usd === "number"
  );
}

/** GET /credit-packs. Pass `currency: "TRY"` for Turkish display prices. */
export async function listCreditPacks(
  params: { currency?: "TRY" } = {},
  options?: RequestOptions,
): Promise<CreditPackCatalog> {
  const query = params.currency ? `?currency=${params.currency}` : "";
  const data = await apiRequest<Partial<CreditPackCatalog>>(`/credit-packs${query}`, {
    options,
  });
  return {
    packs: Array.isArray(data?.packs) ? data.packs.filter(isCreditPack) : [],
    charge_currency: "USD",
    checkout_open: data?.checkout_open === true,
    display_rates: data?.display_rates ?? {},
  };
}

/**
 * POST /credit-packs/{id}/checkout with `channel: "web"`. Returns the hosted
 * checkout URL to open in the browser. Only for builds that may sell outside
 * the store (never call this from an App Store / Play build).
 */
export function startWebCreditPackCheckout(
  packId: string,
  options?: RequestOptions,
): Promise<CreditPackWebCheckout> {
  return apiRequest<CreditPackWebCheckout>(
    `/credit-packs/${encodeURIComponent(packId)}/checkout`,
    { method: "POST", body: { channel: "web" }, options },
  );
}

/**
 * POST /credit-packs/{id}/checkout with `channel: "store"`: ask the server to
 * verify a completed App Store / Play transaction and grant the pack. Safe to
 * retry: a replay returns `already_redeemed: true` without a second grant.
 */
export function redeemCreditPackStorePurchase(
  packId: string,
  purchase: { productId: string; transactionId: string; platform?: string },
  options?: RequestOptions,
): Promise<CreditPackRedemption> {
  return apiRequest<CreditPackRedemption>(
    `/credit-packs/${encodeURIComponent(packId)}/checkout`,
    {
      method: "POST",
      body: {
        channel: "store",
        product_id: purchase.productId,
        transaction_id: purchase.transactionId,
        platform: purchase.platform,
      },
      options: {
        ...options,
        idempotencyKey: `store-credit-${purchase.transactionId}`,
      },
    },
  );
}
