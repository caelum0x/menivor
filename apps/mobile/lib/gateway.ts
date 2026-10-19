/**
 * Typed client for the API-resale gateway — Expo. Mint provisioning keys with a
 * daily cap + markup; the secret is returned exactly once. Mirrors the web
 * `src/features/gateway/api.ts`.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

export interface ProvisioningKey {
  id: string;
  label: string;
  daily_cap_micros: number;
  markup_bps: number;
  min_fee_micros: number;
  disabled: boolean;
  secret?: string;
}

export function listKeys(options?: RequestOptions): Promise<{ keys: ProvisioningKey[] }> {
  return request<{ keys: ProvisioningKey[] }>("/gateway/keys", { options });
}

export function createKey(
  body: { label?: string; daily_cap_micros?: number; markup_bps?: number },
  options?: RequestOptions,
): Promise<ProvisioningKey> {
  return request<ProvisioningKey>("/gateway/keys", { method: "POST", body, options });
}

/** Revoke a provisioning key. Irreversible; the key stops resolving immediately. */
export function revokeKey(
  keyId: string,
  options?: RequestOptions,
): Promise<ProvisioningKey> {
  return request<ProvisioningKey>(
    `/gateway/keys/${encodeURIComponent(keyId)}/revoke`,
    { method: "POST", options },
  );
}

export interface KeyQuote {
  base_cost_micros: number;
  marked_up_micros: number;
  markup_micros: number;
  daily_cap_micros: number;
  daily_used_micros: number;
  daily_remaining_micros: number;
}

/**
 * Preview the marked-up price for a base cost under a key, plus the key's
 * remaining daily allowance. Non-committal — nothing is debited.
 */
export function quoteKey(
  keyId: string,
  body: { base_cost_micros: number },
  options?: RequestOptions,
): Promise<KeyQuote> {
  return request<KeyQuote>(
    `/gateway/keys/${encodeURIComponent(keyId)}/quote`,
    { method: "POST", body, options },
  );
}

export function usd(micros: number): string {
  return `$${(micros / 1_000_000).toFixed(2)}`;
}
