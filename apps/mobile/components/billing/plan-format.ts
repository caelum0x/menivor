/**
 * Pure, dependency-free presentation helpers for the ENTERPRISE Plan & Usage
 * screen (Epic 3 Billing Platform). They turn the raw entitlement / usage shapes
 * returned by `lib/billing.ts` into human copy, order the plan tiers so the
 * screen can offer the *next* tiers up as upgrades, and compute a clamped
 * usage-vs-limit ratio for the progress bars.
 *
 * No network and no secrets here — the values are read straight from the
 * tenant-scoped API payloads. The plan catalogue mirrors
 * `app.services.entitlements.PLAN_ENTITLEMENTS` (free < starter < pro <
 * enterprise); an unknown plan is treated as the base tier so a bad key can only
 * ever *offer* more, never silently unlock it.
 */

import type { PlanKey } from "@/lib/billing";

/** The plan tiers, cheapest → richest. Index doubles as the tier rank. */
export const PLAN_ORDER: readonly PlanKey[] = [
  "free",
  "starter",
  "pro",
  "enterprise",
] as const;

const PLAN_LABELS: Record<PlanKey, string> = {
  free: "Free",
  starter: "Starter",
  pro: "Pro",
  enterprise: "Enterprise",
};

/** Human label for a plan key ("pro" → "Pro"; unknown → Title-cased as-is). */
export function planLabel(planKey: string | null | undefined): string {
  const key = (planKey || "").trim().toLowerCase();
  if (key in PLAN_LABELS) return PLAN_LABELS[key as PlanKey];
  if (!key) return "Free";
  return key.charAt(0).toUpperCase() + key.slice(1);
}

/** Rank of a plan in {@link PLAN_ORDER}; unknown/blank → the base tier (0). */
export function planRank(planKey: string | null | undefined): number {
  const key = (planKey || "").trim().toLowerCase() as PlanKey;
  const idx = PLAN_ORDER.indexOf(key);
  return idx < 0 ? 0 : idx;
}

/**
 * The tiers strictly richer than `current`, cheapest first — the upgrade
 * targets to surface. Empty when the caller is already on the top tier.
 */
export function upgradeTargets(current: string | null | undefined): PlanKey[] {
  return PLAN_ORDER.slice(planRank(current) + 1);
}

// ---------------------------------------------------------------------------
// Entitlement + usage-metric copy
// ---------------------------------------------------------------------------

/** Friendly labels for the known entitlement / metric keys. */
const FEATURE_LABELS: Record<string, string> = {
  max_variants: "Variants per generation",
  api_access: "API access",
  sso: "Single sign-on",
  priority_render: "Priority rendering",
  seats: "Team seats",
  monthly_credits: "Monthly credits",
  watermark_removal: "Watermark removal",
};

/** Human label for an entitlement / usage metric key ("max_variants" → words). */
export function featureLabel(key: string): string {
  const known = FEATURE_LABELS[key];
  if (known) return known;
  const spaced = key.replace(/[_.]+/g, " ").trim();
  if (!spaced) return key;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Render an entitlement value: booleans → Included/Not included, else the value. */
export function entitlementValueLabel(
  value: number | boolean | string,
): string {
  if (typeof value === "boolean") return value ? "Included" : "Not included";
  if (typeof value === "number") return formatInt(value);
  return String(value);
}

/** Whether an entitlement value reads as an "off" capability (greyed in the UI). */
export function isDisabledCapability(value: number | boolean | string): boolean {
  return value === false;
}

/**
 * Fraction of a metric's limit consumed, clamped to [0, 1]. `null` when the
 * metric is unbounded for the plan (no positive limit) so callers can branch.
 */
export function metricRatio(
  used: number,
  limit: number | null | undefined,
): number | null {
  if (typeof limit !== "number" || !Number.isFinite(limit) || limit <= 0) {
    return null;
  }
  const safeUsed = Number.isFinite(used) ? Math.max(0, used) : 0;
  return Math.min(1, safeUsed / limit);
}

/** Thousands-separated integer (Hermes-safe; avoids `Intl`). */
export function formatInt(value: number): string {
  if (!Number.isFinite(value)) return "0";
  const rounded = Math.round(value);
  const negative = rounded < 0;
  const digits = Math.abs(rounded).toString();
  let out = "";
  for (let i = 0; i < digits.length; i += 1) {
    if (i > 0 && (digits.length - i) % 3 === 0) out += ",";
    out += digits[i];
  }
  return negative ? `-${out}` : out;
}

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

/**
 * Format a `"YYYY-MM"` billing period as "Aug 2026". Returns "" for a blank or
 * unparseable value (defensive against a legacy/empty payload).
 */
export function formatPeriod(period: string | null | undefined): string {
  if (!period) return "";
  const match = /^(\d{4})-(\d{2})$/.exec(period.trim());
  if (!match) return "";
  const year = Number(match[1]);
  const monthIndex = Number(match[2]) - 1;
  if (monthIndex < 0 || monthIndex > 11) return "";
  return `${MONTHS[monthIndex]} ${year}`;
}
