/**
 * Typed client for the pay-as-you-go marketplace endpoints (catalog + wallet).
 *
 * Mirrors `docs/reelforge/PROVIDER_MARKETPLACE_PLAN.md` §4.3. Money is integer
 * microdollars on the wire; the wallet never computes fees/prices locally — the
 * server quote is authoritative. `formatUsdMicros` is display-only.
 */

import {
  apiRequest as request,
  type RequestOptions,
} from "@/src/shared/api";

const MICRODOLLARS_PER_USD = 1_000_000;

/** Display-only USD formatting for an integer-microdollar amount. */
export function formatUsdMicros(micros: number | undefined | null): string {
  const value = (micros ?? 0) / MICRODOLLARS_PER_USD;
  return value.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

// --------------------------------------------------------------------------- //
// Types
// --------------------------------------------------------------------------- //
export interface WalletBalance {
  account_id: string;
  currency: string;
  available_micros: number;
  reserved_micros: number;
  available_usd: string;
  reserved_usd: string;
}

export interface WalletActivityEntry {
  id: number | null;
  entry_type: string;
  reason: string;
  available_delta: number;
  reserved_delta: number;
  available_after: number;
  available_after_usd: string;
  job_id: string | null;
  correlation_id: string;
  created_at: string | null;
}

export interface PurchaseQuote {
  credit_micros: number;
  fee_micros: number;
  tax_micros: number;
  processor_micros: number;
  total_charge_micros: number;
  fee_rate_bps: number;
  fee_schedule_version: string;
  currency: string;
}

export interface CatalogModelPrice {
  price_version_id?: string;
  currency?: string;
  unit?: string;
  unit_price_micros?: number;
}

export interface CatalogModel {
  model_id: string;
  capability: string;
  display_name: string;
  description: string;
  metering_unit: string;
  region: string;
  latency_band: string;
  availability_state: string;
  release_status: string;
  provider: { provider_key?: string; display_name?: string; region?: string };
  price: CatalogModelPrice;
}

export interface GenerationProfile {
  slug: string;
  display_name: string;
  description: string;
  stages: Record<string, unknown>;
  routing: Record<string, unknown>;
  max_cost_micros: number;
  is_curated: boolean;
}

export interface GenerationQuoteStage {
  stage: string;
  model_id: string;
  provider_key: string;
  unit: string;
  quantity_units: number;
  cost_micros: number;
}

export interface GenerationQuote {
  quote_id: string;
  profile: string;
  currency: string;
  stages: GenerationQuoteStage[];
  total_micros: number;
  max_cost_micros: number;
  cap_micros: number | null;
  within_budget: boolean;
  expires_at: string;
  signature: string;
}

// --------------------------------------------------------------------------- //
// Wallet
// --------------------------------------------------------------------------- //
/** GET /wallet — balance snapshot (available + reserved). */
export function getWallet(options?: RequestOptions): Promise<WalletBalance> {
  return request<WalletBalance>("/wallet", { options });
}

/** GET /wallet/activity — ledger activity, newest first. */
export async function getWalletActivity(
  options?: RequestOptions,
  limit = 50,
): Promise<WalletActivityEntry[]> {
  const data = await request<
    WalletActivityEntry[] | { activity?: WalletActivityEntry[] }
  >(`/wallet/activity?limit=${encodeURIComponent(String(limit))}`, { options });
  if (Array.isArray(data)) return data;
  return data?.activity ?? [];
}

/** POST /wallet/purchase-quotes — checkout money breakdown (no charge). */
export function requestPurchaseQuote(
  amountUsd: string,
  options?: RequestOptions,
): Promise<PurchaseQuote> {
  return request<PurchaseQuote>("/wallet/purchase-quotes", {
    method: "POST",
    body: { amount_usd: amountUsd },
    options,
  });
}

// --------------------------------------------------------------------------- //
// Catalog
// --------------------------------------------------------------------------- //
/** GET /catalog/models — reviewed model listings (optional capability filter). */
export async function listCatalogModels(
  options?: RequestOptions,
  capability?: string,
): Promise<CatalogModel[]> {
  const query = capability
    ? `?capability=${encodeURIComponent(capability)}`
    : "";
  const data = await request<CatalogModel[] | { models?: CatalogModel[] }>(
    `/catalog/models${query}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.models ?? [];
}

/** GET /catalog/profiles — curated + caller-owned generation profiles. */
export async function listGenerationProfiles(
  options?: RequestOptions,
): Promise<GenerationProfile[]> {
  const data = await request<
    GenerationProfile[] | { profiles?: GenerationProfile[] }
  >("/catalog/profiles", { options });
  if (Array.isArray(data)) return data;
  return data?.profiles ?? [];
}

/** POST /catalog/quotes/generation — signed, versioned price snapshot. */
export function requestGenerationQuote(
  body: { profile?: string; stages?: Record<string, string>; max_cost_usd?: string },
  options?: RequestOptions,
): Promise<GenerationQuote> {
  return request<GenerationQuote>("/catalog/quotes/generation", {
    method: "POST",
    body,
    options,
  });
}

// --------------------------------------------------------------------------- //
// Spend policy + usage analytics (enterprise controls)
// --------------------------------------------------------------------------- //
export interface SpendPolicy {
  scope: "user" | "workspace";
  monthly_budget_micros: number;
  byok_allowed: boolean;
  spend_min_role?: string;
  period_spend_micros: number;
}

export interface SpendPolicyUpdate {
  monthly_budget_micros?: number;
  byok_allowed?: boolean;
  spend_min_role?: "owner" | "admin" | "member";
}

export interface UsageGroup {
  key: string;
  cost_micros: number;
  cost_usd: string;
  runs: number;
  units: number;
}

export interface UsageSummary {
  scope: "user" | "workspace";
  days: number;
  total_cost_micros: number;
  total_cost_usd: string;
  by_model: UsageGroup[];
  by_provider: UsageGroup[];
  by_stage: UsageGroup[];
  by_day: UsageGroup[];
}

function scoped(path: string, workspaceId?: string): string {
  return workspaceId ? `${path}?workspace_id=${encodeURIComponent(workspaceId)}` : path;
}

/** GET /spend/policy — budget cap + BYOK consent (+ period spend). */
export function getSpendPolicy(
  options?: RequestOptions,
  workspaceId?: string,
): Promise<SpendPolicy> {
  return request<SpendPolicy>(scoped("/spend/policy", workspaceId), { options });
}

/** PUT /spend/policy — update budget / BYOK consent / spend role. */
export function updateSpendPolicy(
  body: SpendPolicyUpdate,
  options?: RequestOptions,
  workspaceId?: string,
): Promise<SpendPolicy> {
  return request<SpendPolicy>(scoped("/spend/policy", workspaceId), {
    method: "PUT",
    body,
    options,
  });
}

/** GET /insights/usage — cost attribution by model/provider/stage/day. */
export function getUsageSummary(
  options?: RequestOptions,
  days = 30,
  workspaceId?: string,
): Promise<UsageSummary> {
  const ws = workspaceId ? `&workspace_id=${encodeURIComponent(workspaceId)}` : "";
  return request<UsageSummary>(`/insights/usage?days=${days}${ws}`, { options });
}

// --------------------------------------------------------------------------- //
// Provider health / status
// --------------------------------------------------------------------------- //
export interface ProviderHealth {
  provider_key: string;
  window_h: number;
  samples: number;
  uptime: number;
  avg_latency_ms: number;
  state: "healthy" | "degraded" | "down" | "unknown";
}

/** GET /catalog/providers/health — public provider status. */
export async function getProviderHealth(
  options?: RequestOptions,
  windowH = 24,
): Promise<ProviderHealth[]> {
  const data = await request<{ providers?: ProviderHealth[] } | ProviderHealth[]>(
    `/catalog/providers/health?window_h=${windowH}`,
    { options, anonymous: true },
  );
  if (Array.isArray(data)) return data;
  return data?.providers ?? [];
}

/** A model listing enriched with its provider's rolling health, for comparison. */
export interface CompareModel extends CatalogModel {
  health?: {
    uptime?: number;
    avg_latency_ms?: number;
    state?: "healthy" | "degraded" | "down" | "unknown";
    samples?: number;
  };
}

/** GET /catalog/models/compare — models by capability with price + health. */
export async function compareModels(
  capability: string,
  sort: "price" | "latency" = "price",
  options?: RequestOptions,
): Promise<CompareModel[]> {
  const data = await request<{ models?: CompareModel[] } | CompareModel[]>(
    `/catalog/models/compare?capability=${encodeURIComponent(capability)}&sort=${sort}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.models ?? [];
}

// --------------------------------------------------------------------------- //
// Camera-motion + VFX presets (Higgsfield-class creation)
// --------------------------------------------------------------------------- //
export interface MotionPreset {
  id: string;
  name: string;
  category: string;
  description: string;
  tags: string[];
}

export interface VfxPreset {
  id: string;
  name: string;
  category: string;
  description: string;
  tags: string[];
}

/** GET /catalog/motion-presets — one-click camera moves. */
export async function listMotionPresets(options?: RequestOptions): Promise<MotionPreset[]> {
  const data = await request<{ camera_motions?: MotionPreset[] }>(
    "/catalog/motion-presets",
    { options, anonymous: true },
  );
  return data?.camera_motions ?? [];
}

/** GET /catalog/vfx-presets — stackable VFX (Effects Mix). Returns [presets, maxStack]. */
export async function listVfxPresets(
  options?: RequestOptions,
): Promise<{ vfx: VfxPreset[]; maxStack: number }> {
  const data = await request<{ vfx?: VfxPreset[]; max_stack?: number }>(
    "/catalog/vfx-presets",
    { options, anonymous: true },
  );
  return { vfx: data?.vfx ?? [], maxStack: data?.max_stack ?? 4 };
}
