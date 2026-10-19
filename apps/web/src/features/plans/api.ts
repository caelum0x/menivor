/**
 * Personal monthly plans (Creator / Pro / Agency) on the web, billed by the active payment provider (Dodo Payments).
 * Thin wrappers over the Menivor API plus pure helpers for the upsell copy.
 * Mobile uses RevenueCat and never calls these.
 */

import { API_BASE, ApiError, apiRequest, type RequestOptions } from "@/src/shared/api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type PlanKey = "creator" | "pro" | "agency";
export type PlanInterval = "month" | "year";

export interface MonthlyPlan {
  readonly plan_key: PlanKey;
  readonly name: string;
  readonly rank: number;
  readonly monthly_cents: number;
  readonly yearly_cents: number;
  readonly monthly_reels: number;
  readonly yearly_reels: number;
  readonly per_reel_cents: Readonly<Record<PlanInterval, number>>;
  readonly available: Readonly<Record<PlanInterval, boolean>>;
}

export interface MonthlyCatalog {
  readonly plans: readonly MonthlyPlan[];
  readonly yearly_months_charged: number;
  readonly best_pack_per_reel_cents: number;
}

export interface MyPlan {
  readonly plan: {
    readonly plan_key: PlanKey;
    readonly name: string;
    readonly interval: PlanInterval;
    readonly price_cents: number;
    readonly period_reels: number;
  } | null;
  readonly status: string;
  readonly renews: boolean;
  readonly cancel_at_period_end: boolean;
  readonly current_period_end: string | null;
  readonly included_left: number;
  readonly credits: number;
  readonly reels_used_30d: number;
  /** Lifetime finished renders; absent on APIs that predate it. */
  readonly reels_rendered?: number;
  readonly can_manage: boolean;
  readonly low_credits: boolean;
  readonly recommended_plan: PlanKey | null;
}

/**
 * Which intervals the display fallback treats as on sale, from
 * `NEXT_PUBLIC_MONTHLY_PLANS_ON_SALE` ("1"/"true"/"month,year" = both,
 * "month" = monthly only; unset = neither). The live catalog always wins; this
 * only decides what the page says when the API could not be reached at render.
 * Checkout re-validates server-side either way.
 */
export function fallbackAvailability(raw: string | undefined): Readonly<Record<PlanInterval, boolean>> {
  const value = (raw ?? "").trim().toLowerCase();
  if (value === "1" || value === "true" || value === "yes" || value === "all") {
    return { month: true, year: true };
  }
  const parts = new Set(value.split(/[\s,]+/).filter(Boolean));
  return { month: parts.has("month"), year: parts.has("year") };
}

const FALLBACK_AVAILABLE = fallbackAvailability(process.env.NEXT_PUBLIC_MONTHLY_PLANS_ON_SALE);

function plan(
  key: PlanKey,
  name: string,
  rank: number,
  monthlyCents: number,
  reels: number,
): MonthlyPlan {
  return {
    plan_key: key,
    name,
    rank,
    monthly_cents: monthlyCents,
    yearly_cents: monthlyCents * 10,
    monthly_reels: reels,
    yearly_reels: reels * 12,
    per_reel_cents: {
      month: Math.round(monthlyCents / reels),
      year: Math.round((monthlyCents * 10) / (reels * 12)),
    },
    available: FALLBACK_AVAILABLE,
  };
}

/**
 * Display defaults mirroring apps/api/app/services/billing/creator_plans.py,
 * used only when the live catalog cannot be read (API down at render time).
 * `available` comes from {@link fallbackAvailability}; the live catalog, read
 * on the server by {@link loadCatalogForRender}, is what the page normally
 * renders with.
 */
export const FALLBACK_CATALOG: MonthlyCatalog = {
  plans: [
    plan("creator", "Creator", 1, 1500, 35),
    plan("pro", "Pro", 2, 3900, 100),
    plan("agency", "Agency", 3, 9900, 300),
  ],
  yearly_months_charged: 10,
  best_pack_per_reel_cents: 49,
};

const PLAN_KEYS: readonly PlanKey[] = ["creator", "pro", "agency"];

function cents(value: unknown): number | null {
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? Math.round(n) : null;
}

function planFrom(raw: unknown): MonthlyPlan | null {
  if (typeof raw !== "object" || raw === null) return null;
  const rec = raw as Record<string, unknown>;
  const key = rec.plan_key as PlanKey;
  if (!PLAN_KEYS.includes(key)) return null;
  const monthly = cents(rec.monthly_cents);
  const yearly = cents(rec.yearly_cents);
  const monthlyReels = cents(rec.monthly_reels);
  const yearlyReels = cents(rec.yearly_reels);
  if (monthly === null || yearly === null || !monthlyReels || !yearlyReels) return null;
  const perReel = (rec.per_reel_cents ?? {}) as Record<string, unknown>;
  const available = (rec.available ?? {}) as Record<string, unknown>;
  return {
    plan_key: key,
    name: typeof rec.name === "string" && rec.name ? rec.name : key,
    rank: cents(rec.rank) ?? 0,
    monthly_cents: monthly,
    yearly_cents: yearly,
    monthly_reels: monthlyReels,
    yearly_reels: yearlyReels,
    per_reel_cents: {
      month: cents(perReel.month) ?? Math.round(monthly / monthlyReels),
      year: cents(perReel.year) ?? Math.round(yearly / yearlyReels),
    },
    // Only an explicit `true` from the API puts a plan on sale.
    available: { month: available.month === true, year: available.year === true },
  };
}

/**
 * Normalize the `GET /billing/monthly-plans` payload (network input), or
 * `null` when it has no usable plans.
 */
export function catalogFrom(raw: unknown): MonthlyCatalog | null {
  if (typeof raw !== "object" || raw === null) return null;
  const rec = raw as Record<string, unknown>;
  const plans = Array.isArray(rec.plans)
    ? rec.plans.map(planFrom).filter((p): p is MonthlyPlan => p !== null)
    : [];
  if (!plans.length) return null;
  return {
    plans,
    yearly_months_charged:
      cents(rec.yearly_months_charged) || FALLBACK_CATALOG.yearly_months_charged,
    best_pack_per_reel_cents:
      cents(rec.best_pack_per_reel_cents) ?? FALLBACK_CATALOG.best_pack_per_reel_cents,
  };
}

export async function getMonthlyCatalog(): Promise<MonthlyCatalog> {
  const data = await apiRequest<unknown>("/billing/monthly-plans", { anonymous: true });
  return catalogFrom(data) ?? FALLBACK_CATALOG;
}

/** How long the server waits for the catalog before rendering the fallback. */
export const RENDER_CATALOG_TIMEOUT_MS = 2500;

/**
 * The live catalog for server rendering, so the first HTML (and anyone without
 * JavaScript, including crawlers) shows the real on-sale state instead of the
 * display fallback. Never throws: returns `null` when the API is unreachable,
 * slow or malformed, and the caller renders {@link FALLBACK_CATALOG}.
 */
export async function loadCatalogForRender(
  fetchImpl: typeof fetch = fetch,
  base: string = API_BASE,
): Promise<MonthlyCatalog | null> {
  try {
    const response = await fetchImpl(`${base}/billing/monthly-plans`, {
      cache: "no-store",
      signal: AbortSignal.timeout(RENDER_CATALOG_TIMEOUT_MS),
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return null;
    const envelope = (await response.json()) as { data?: unknown } | null;
    return catalogFrom(envelope?.data);
  } catch {
    return null;
  }
}

/** My plan, or `null` when the API predates monthly plans (404). */
export async function getMyPlan(options: RequestOptions): Promise<MyPlan | null> {
  try {
    return await apiRequest<MyPlan>("/billing/monthly-plan", { options });
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export function startPlanCheckout(
  planKey: PlanKey,
  interval: PlanInterval,
  options: RequestOptions,
): Promise<{ checkout_url: string }> {
  return apiRequest("/billing/monthly-plan/checkout", {
    method: "POST",
    body: { plan_key: planKey, interval },
    options,
  });
}

export function changePlan(planKey: PlanKey, options: RequestOptions): Promise<MyPlan> {
  return apiRequest("/billing/monthly-plan/change", {
    method: "POST",
    body: { plan_key: planKey },
    options,
  });
}

export function cancelPlan(options: RequestOptions): Promise<MyPlan> {
  return apiRequest("/billing/monthly-plan/cancel", { method: "POST", options });
}

export function openBillingPortal(options: RequestOptions): Promise<{ url: string }> {
  return apiRequest("/billing/monthly-plan/portal", { method: "POST", options });
}

/** `$15`, `$0.43`. Whole dollars drop the cents. */
export function formatUsd(cents: number): string {
  const dollars = cents / 100;
  return Number.isInteger(dollars) ? `$${dollars}` : `$${dollars.toFixed(2)}`;
}

/** `Oct 25, 2026` from an ISO date (empty when missing/invalid). */
export function formatDate(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/** The plan to pitch: the API's recommendation, else the cheapest plan. */
export function pickPlan(catalog: MonthlyCatalog, recommended: PlanKey | null | undefined): MonthlyPlan {
  const plans = catalog.plans.length ? catalog.plans : FALLBACK_CATALOG.plans;
  return plans.find((p) => p.plan_key === recommended) ?? plans[0]!;
}

/** Percent cheaper per reel than the best pack (0 when not cheaper). */
export function savingsVsPacks(plan: MonthlyPlan, interval: PlanInterval, bestPackCents: number): number {
  const per = plan.per_reel_cents[interval];
  if (!bestPackCents || per >= bestPackCents) return 0;
  return Math.round(((bestPackCents - per) / bestPackCents) * 100);
}

/** Readable copy for plan/billing errors. */
export function planErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return "We could not reach Menivor. Check your connection and try again.";
    if (err.status === 401) return "Your session expired. Sign in again to continue.";
    if (err.status === 403) return "Monthly plans are not on sale yet. Credit packs work in the meantime.";
    return friendlyErrorMessage(err, "Something went wrong. Try again.");
  }
  return friendlyErrorMessage(err, "Something went wrong. Try again.");
}

// --------------------------------------------------------------------------- //
// Premium voice and AI-video packs (one-time, separate balances)
// --------------------------------------------------------------------------- //

export type PremiumKind = "premium_voice" | "ai_video";

export interface PremiumPack {
  readonly key: string;
  readonly kind: PremiumKind;
  readonly credits: number;
  readonly price_usd: number;
  readonly available: boolean;
}

export interface PremiumStatus {
  readonly balances: Readonly<Record<PremiumKind, number>> & { readonly unavailable?: boolean };
  readonly packs: readonly PremiumPack[];
}

const PREMIUM_KINDS: readonly PremiumKind[] = ["premium_voice", "ai_video"];

/** Normalize `GET /billing/premium` (network input). */
export function premiumStatusFrom(raw: unknown): PremiumStatus {
  const rec = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  const rawBalances = (rec.balances ?? {}) as Record<string, unknown>;
  const packs = Array.isArray(rec.packs)
    ? rec.packs.flatMap((item): PremiumPack[] => {
        if (typeof item !== "object" || item === null) return [];
        const p = item as Record<string, unknown>;
        const kind = p.kind as PremiumKind;
        const credits = cents(p.credits);
        const price = Number(p.price_usd);
        if (typeof p.key !== "string" || !PREMIUM_KINDS.includes(kind) || !credits) return [];
        if (!Number.isFinite(price) || price <= 0) return [];
        return [{ key: p.key, kind, credits, price_usd: price, available: p.available === true }];
      })
    : [];
  return {
    balances: {
      premium_voice: cents(rawBalances.premium_voice) ?? 0,
      ai_video: cents(rawBalances.ai_video) ?? 0,
      unavailable: rawBalances.unavailable === true,
    },
    packs,
  };
}

export async function getPremiumStatus(options: RequestOptions): Promise<PremiumStatus> {
  return premiumStatusFrom(await apiRequest<unknown>("/billing/premium", { options }));
}

export function startPremiumCheckout(
  packKey: string,
  options: RequestOptions,
): Promise<{ checkout_url: string }> {
  return apiRequest("/billing/premium/checkout", {
    method: "POST",
    body: { pack_key: packKey },
    options,
  });
}
