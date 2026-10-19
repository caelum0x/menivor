/**
 * API-resale gateway client — provisioning keys (daily cap + markup), revoke,
 * and price quotes.
 *
 * Every call flows through the shared authenticated transport (`apiRequest`),
 * which unwraps the MPT `{ data }` envelope and raises `ApiError` on failure.
 * The mutating `createKey` accepts an `idempotencyKey` (via `RequestOptions`)
 * so an ambiguous transport retry never mints a duplicate key.
 *
 * Wired to the gateway domain:
 *   GET  /gateway/keys                    listKeys
 *   POST /gateway/keys                    createKey (Idempotency-Key)
 *   POST /gateway/keys/{key_id}/revoke    revokeKey
 *   POST /gateway/keys/{key_id}/quote     quoteKey
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

/** A reseller provisioning key with a daily spend cap + markup policy. */
export interface ProvisioningKey {
  id: string;
  label: string;
  daily_cap_micros: number;
  markup_bps: number;
  min_fee_micros: number;
  disabled: boolean;
  /** Plaintext secret — present ONLY on the create response, shown once. */
  secret?: string;
}

/** Body for minting a new provisioning key. */
export interface CreateKeyBody {
  label?: string;
  daily_cap_micros?: number;
  markup_bps?: number;
  min_fee_micros?: number;
}

/** A marked-up price preview + remaining daily allowance for a key. */
export interface Quote {
  base_cost_micros: number;
  customer_price_micros: number;
  spent_today_micros: number;
  /** `-1` means the key is unlimited (no daily cap). */
  remaining_micros: number;
  would_allow: boolean;
}

/** GET /gateway/keys — the caller's provisioning keys (never returns secrets). */
export function listKeys(
  options?: RequestOptions,
): Promise<{ keys: ProvisioningKey[] }> {
  return apiRequest<{ keys: ProvisioningKey[] }>("/gateway/keys", { options });
}

/** POST /gateway/keys — mint a key; the secret is returned exactly once. */
export function createKey(
  body: CreateKeyBody,
  options?: RequestOptions,
): Promise<ProvisioningKey> {
  return apiRequest<ProvisioningKey>("/gateway/keys", {
    method: "POST",
    body,
    options,
  });
}

/** POST /gateway/keys/{key_id}/revoke — disable a key. Returns the updated key. */
export function revokeKey(
  keyId: string,
  options?: RequestOptions,
): Promise<ProvisioningKey> {
  return apiRequest<ProvisioningKey>(
    `/gateway/keys/${encodeURIComponent(keyId)}/revoke`,
    { method: "POST", options },
  );
}

/** POST /gateway/keys/{key_id}/quote — preview the customer price for a base cost. */
export function quoteKey(
  keyId: string,
  baseCostMicros: number,
  options?: RequestOptions,
): Promise<Quote> {
  return apiRequest<Quote>(
    `/gateway/keys/${encodeURIComponent(keyId)}/quote`,
    {
      method: "POST",
      body: { base_cost_micros: baseCostMicros },
      options,
    },
  );
}

const MICROS_PER_USD = 1_000_000;

/** Integer USD-cents/dollars → microdollars (the wallet's money unit). */
export function usdToMicros(usd: number): number {
  return Math.round(usd * MICROS_PER_USD);
}

/** Microdollars → a compact `$x.xx` display string. */
export function microsToUsd(micros: number): string {
  return `$${(micros / MICROS_PER_USD).toFixed(2)}`;
}

/** Basis points → a `x.x%` display string (100 bps = 1%). */
export function bpsToPercent(bps: number): string {
  return `${(bps / 100).toFixed(1)}%`;
}
