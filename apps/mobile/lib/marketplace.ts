/**
 * Typed client for the pay-as-you-go marketplace (catalog + wallet) — Expo.
 *
 * Mirrors `docs/reelforge/PROVIDER_MARKETPLACE_PLAN.md` §4.3 and the web client.
 * Money is integer microdollars on the wire; the wallet never computes fees or
 * prices locally — the server quote is authoritative. `formatUsdMicros` is
 * display-only.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

const MICRODOLLARS_PER_USD = 1_000_000;

/** Display-only USD formatting for an integer-microdollar amount. */
export function formatUsdMicros(micros: number | undefined | null): string {
  const value = (micros ?? 0) / MICRODOLLARS_PER_USD;
  return `$${value.toFixed(2)}`;
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
  available_after_usd: string;
  job_id: string | null;
  created_at: string | null;
}

export interface CatalogModel {
  model_id: string;
  capability: string;
  display_name: string;
  metering_unit: string;
  availability_state: string;
  provider: { provider_key?: string; display_name?: string };
  price: { unit?: string; unit_price_micros?: number };
}

export interface GenerationProfile {
  slug: string;
  display_name: string;
  description: string;
  max_cost_micros: number;
  is_curated: boolean;
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

// --------------------------------------------------------------------------- //
// Catalog
// --------------------------------------------------------------------------- //
/** GET /catalog/models — reviewed model listings (optional capability filter). */
export async function listCatalogModels(
  options?: RequestOptions,
  capability?: string,
): Promise<CatalogModel[]> {
  const query = capability ? `?capability=${encodeURIComponent(capability)}` : "";
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

// --------------------------------------------------------------------------- //
// Spend policy + usage analytics
// --------------------------------------------------------------------------- //
export interface SpendPolicy {
  scope: "user" | "workspace";
  monthly_budget_micros: number;
  byok_allowed: boolean;
  period_spend_micros: number;
}

export interface UsageGroup {
  key: string;
  cost_micros: number;
  cost_usd: string;
  runs: number;
}

export interface UsageSummary {
  days: number;
  total_cost_micros: number;
  total_cost_usd: string;
  by_provider: UsageGroup[];
  by_stage: UsageGroup[];
}

/** GET /spend/policy — budget cap + BYOK consent (+ period spend). */
export function getSpendPolicy(options?: RequestOptions): Promise<SpendPolicy> {
  return request<SpendPolicy>("/spend/policy", { options });
}

/** Fields accepted by PUT /spend/policy; omitted fields stay unchanged. */
export interface SpendPolicyUpdate {
  /** Monthly cap in USD micros; 0 removes the cap. */
  monthly_budget_micros?: number;
  byok_allowed?: boolean;
}

/** PUT /spend/policy — update the caller's personal budget cap / BYOK consent. */
export function updateSpendPolicy(
  body: SpendPolicyUpdate,
  options?: RequestOptions,
): Promise<SpendPolicy> {
  return request<SpendPolicy>("/spend/policy", { method: "PUT", body, options });
}

/** GET /insights/usage — cost attribution over a window. */
export function getUsageSummary(options?: RequestOptions, days = 30): Promise<UsageSummary> {
  return request<UsageSummary>(`/insights/usage?days=${days}`, { options });
}

// --------------------------------------------------------------------------- //
// Model catalog — live compare, single-model detail, provider health, presets,
// and the pre-render generation cost quote. Mirrors the web client
// (apps/web/lib/marketplace.ts) and the catalog router under /catalog/*.
// --------------------------------------------------------------------------- //

/** Non-sensitive provider fields carried by a model listing / detail view. */
export interface CatalogProviderView {
  provider_key: string;
  display_name: string;
  region?: string;
  data_policy?: string;
  health_state?: string;
}

/** Full active-price breakdown for a single reviewed model listing. */
export interface CatalogPriceView {
  price_version_id?: string;
  currency?: string;
  unit?: string;
  unit_price_micros?: number;
  min_charge_micros?: number;
  flat_fee_micros?: number;
  version?: number;
}

/** One reviewed model listing with the full detail payload (GET /catalog/models/{id}). */
export interface CatalogModelDetail {
  model_id: string;
  capability: string;
  display_name: string;
  description: string;
  metering_unit: string;
  supported_inputs: string[];
  output_limits: Record<string, unknown>;
  region: string;
  data_policy: string;
  latency_band: string;
  availability_state: string;
  release_status: string;
  provider: CatalogProviderView;
  price: CatalogPriceView;
}

/** Normalized provider health / uptime state. */
export type ProviderHealthState = "healthy" | "degraded" | "down" | "unknown";

/** Public provider status (GET /catalog/providers/health). */
export interface ProviderHealth {
  provider_key: string;
  window_h: number;
  samples: number;
  uptime: number;
  avg_latency_ms: number;
  state: ProviderHealthState;
}

/** The rolling-health block attached to each row in a model comparison. */
export interface CompareModelHealth {
  provider_key?: string;
  window_h?: number;
  samples?: number;
  uptime?: number;
  avg_latency_ms?: number;
  state?: ProviderHealthState;
}

/** A model listing enriched with its provider's health, for side-by-side compare. */
export interface CompareModel extends CatalogModel {
  description?: string;
  latency_band?: string;
  health?: CompareModelHealth;
}

/** Sort key for the compare endpoint. */
export type CompareSort = "price" | "latency";

/** One priced stage inside a signed generation quote. */
export interface GenerationQuoteStage {
  stage: string;
  model_id: string;
  provider_key: string;
  capability?: string;
  unit: string;
  unit_price_micros?: number;
  quantity_units: number;
  cost_micros: number;
  price_version?: number;
}

/** A signed, versioned generation price snapshot (POST /catalog/quotes/generation). */
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

/** Request body for a generation quote — a profile slug or an ad-hoc stage map. */
export interface GenerationQuoteRequestBody {
  profile?: string;
  stages?: Record<string, string>;
  estimates?: Record<string, number>;
  max_cost_usd?: string;
  workspace_id?: string;
}

/** A one-click camera-motion preset (GET /catalog/motion-presets). */
export interface MotionPreset {
  id: string;
  name: string;
  category: string;
  description: string;
  tags: string[];
}

/** A stackable cinematic VFX preset (GET /catalog/vfx-presets). */
export interface VfxPreset {
  id: string;
  name: string;
  category: string;
  description: string;
  tags: string[];
}

/**
 * Encode a catalog model id for use in a `{model_id:path}` route segment.
 * Model ids may legitimately contain `/` (e.g. `vendor/model`), so each path
 * segment is encoded individually and the slashes are preserved.
 */
function encodeModelId(modelId: string): string {
  return modelId
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

/** GET /catalog/models/{id} — one reviewed listing with provider + active price. */
export function getCatalogModelDetail(
  modelId: string,
  options?: RequestOptions,
): Promise<CatalogModelDetail> {
  return request<CatalogModelDetail>(
    `/catalog/models/${encodeModelId(modelId)}`,
    { options },
  );
}

/** GET /catalog/models/compare — models for a capability with price + health, sorted. */
export async function compareModels(
  capability: string,
  sort: CompareSort = "price",
  options?: RequestOptions,
): Promise<CompareModel[]> {
  const query = `?capability=${encodeURIComponent(capability)}&sort=${encodeURIComponent(sort)}`;
  const data = await request<CompareModel[] | { models?: CompareModel[] }>(
    `/catalog/models/compare${query}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.models ?? [];
}

/** GET /catalog/providers/health — public provider status over a window. */
export async function getProviderHealth(
  options?: RequestOptions,
  windowH = 24,
): Promise<ProviderHealth[]> {
  const data = await request<ProviderHealth[] | { providers?: ProviderHealth[] }>(
    `/catalog/providers/health?window_h=${encodeURIComponent(String(windowH))}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.providers ?? [];
}

/** POST /catalog/quotes/generation — resolve a profile/stage map into a signed quote. */
export function requestGenerationQuote(
  body: GenerationQuoteRequestBody,
  options?: RequestOptions,
): Promise<GenerationQuote> {
  return request<GenerationQuote>("/catalog/quotes/generation", {
    method: "POST",
    body,
    options,
  });
}

/** GET /catalog/motion-presets — one-click camera-motion presets. */
export async function listMotionPresets(options?: RequestOptions): Promise<MotionPreset[]> {
  const data = await request<MotionPreset[] | { camera_motions?: MotionPreset[] }>(
    "/catalog/motion-presets",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.camera_motions ?? [];
}

/** GET /catalog/vfx-presets — stackable VFX presets (Effects Mix) + the stack cap. */
export async function listVfxPresets(
  options?: RequestOptions,
): Promise<{ vfx: VfxPreset[]; maxStack: number }> {
  const data = await request<VfxPreset[] | { vfx?: VfxPreset[]; max_stack?: number }>(
    "/catalog/vfx-presets",
    { options },
  );
  if (Array.isArray(data)) return { vfx: data, maxStack: 4 };
  return { vfx: data?.vfx ?? [], maxStack: data?.max_stack ?? 4 };
}
