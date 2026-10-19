/**
 * Pure, framework-free helpers for the ClipMarket Marketplace & Earnings flows.
 *
 * Kept separate from the React screens so USD↔micros conversion, form
 * validation, campaign lifecycle transitions, and earnings aggregation can be
 * unit-tested without a renderer. No network, no state, no mutation.
 */

import type {
  Campaign,
  CampaignStatus,
  CreateCampaignBody,
  ReviewBody,
} from "@/lib/clipmarket";

/** 1 USD = 1_000_000 micros. */
export const USD_TO_MICROS = 1_000_000;

/**
 * Parse a decimal USD string into integer micros. Returns `null` for anything
 * that is not a finite, non-negative number so callers can surface a field
 * error instead of sending garbage to the API.
 */
export function usdToMicros(usd: string): number | null {
  const trimmed = usd.trim();
  if (trimmed.length === 0) return null;
  const value = Number(trimmed);
  if (!Number.isFinite(value) || value < 0) return null;
  return Math.round(value * USD_TO_MICROS);
}

export interface CampaignFormInput {
  title: string;
  cpmUsd: string;
  budgetUsd: string;
  minViews?: string;
}

export type ParseResult<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly error: string };

/**
 * Validate the "new campaign" form and produce a {@link CreateCampaignBody}.
 * CPM and budget must be positive; `min_views` (optional) must be a
 * non-negative integer. Returns a discriminated result — never throws.
 */
export function parseCampaignForm(
  input: CampaignFormInput,
): ParseResult<CreateCampaignBody> {
  const cpmMicros = usdToMicros(input.cpmUsd);
  if (cpmMicros === null || cpmMicros <= 0) {
    return { ok: false, error: "Enter a valid CPM in USD." };
  }
  const budgetMicros = usdToMicros(input.budgetUsd);
  if (budgetMicros === null || budgetMicros <= 0) {
    return { ok: false, error: "Enter a valid budget in USD." };
  }

  let minViews: number | undefined;
  const rawMin = (input.minViews ?? "").trim();
  if (rawMin.length > 0) {
    const parsed = Number(rawMin);
    if (!Number.isInteger(parsed) || parsed < 0) {
      return { ok: false, error: "Minimum views must be a whole number ≥ 0." };
    }
    minViews = parsed;
  }

  const title = input.title.trim();
  return {
    ok: true,
    value: {
      ...(title ? { title } : {}),
      cpm_micros: cpmMicros,
      budget_micros: budgetMicros,
      ...(minViews !== undefined ? { min_views: minViews } : {}),
    },
  };
}

/**
 * Basic clip-URL guard for the submit form: require an absolute http(s) URL so
 * we fail fast on the client before the round-trip. Server still validates.
 */
export function isHttpUrl(value: string): boolean {
  const trimmed = value.trim();
  if (trimmed.length === 0) return false;
  try {
    const url = new URL(trimmed);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * The lifecycle transitions available from a campaign's current status, as
 * (target status, action label) pairs for rendering moderation buttons. An
 * ended campaign is terminal (no transitions).
 */
export function statusActions(
  status: string,
): ReadonlyArray<{ status: CampaignStatus; label: string }> {
  switch (status) {
    case "active":
      return [
        { status: "paused", label: "Pause" },
        { status: "ended", label: "End" },
      ];
    case "paused":
      return [
        { status: "active", label: "Resume" },
        { status: "ended", label: "End" },
      ];
    default:
      return [];
  }
}

export interface SpendSummary {
  totalSpentMicros: number;
  totalBudgetMicros: number;
  remainingMicros: number;
  activeCount: number;
  campaignCount: number;
}

/**
 * Aggregate spend across a brand's campaigns for the Earnings screen. Pure
 * reduction over `spent_micros` / `budget_micros`; remaining is clamped at 0 so
 * an over-delivered campaign never shows a negative budget.
 */
export function summarizeSpend(
  campaigns: readonly Campaign[],
): SpendSummary {
  const totals = campaigns.reduce(
    (acc, c) => ({
      spent: acc.spent + (c.spent_micros || 0),
      budget: acc.budget + (c.budget_micros || 0),
      active: acc.active + (c.status === "active" ? 1 : 0),
    }),
    { spent: 0, budget: 0, active: 0 },
  );
  return {
    totalSpentMicros: totals.spent,
    totalBudgetMicros: totals.budget,
    remainingMicros: Math.max(0, totals.budget - totals.spent),
    activeCount: totals.active,
    campaignCount: campaigns.length,
  };
}

export interface ReviewFormInput {
  views: string;
  velocityZscore?: string;
  avgWatchFrac?: string;
  engagementRate?: string;
  geoConcentration?: string;
  retentionCliff?: string;
}

function optionalNumber(raw: string | undefined): number | undefined | null {
  const trimmed = (raw ?? "").trim();
  if (trimmed.length === 0) return undefined; // omit → server default 0
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null; // null → invalid
}

/**
 * Validate the reviewer form into a {@link ReviewBody}. `views` is required and
 * must be a non-negative integer; each fraud signal is optional and, when
 * supplied, must be a finite number (omitted fields default to 0 server-side).
 */
export function parseReviewForm(
  input: ReviewFormInput,
): ParseResult<ReviewBody> {
  const viewsRaw = input.views.trim();
  const views = Number(viewsRaw);
  if (viewsRaw.length === 0 || !Number.isInteger(views) || views < 0) {
    return { ok: false, error: "Verified views must be a whole number ≥ 0." };
  }

  const signals: Array<[keyof ReviewBody, string | undefined]> = [
    ["velocity_zscore", input.velocityZscore],
    ["avg_watch_frac", input.avgWatchFrac],
    ["engagement_rate", input.engagementRate],
    ["geo_concentration", input.geoConcentration],
    ["retention_cliff", input.retentionCliff],
  ];

  const body: ReviewBody = { views };
  for (const [key, raw] of signals) {
    const parsed = optionalNumber(raw);
    if (parsed === null) {
      return { ok: false, error: `Signal "${key}" must be a number.` };
    }
    if (parsed !== undefined) {
      body[key] = parsed;
    }
  }
  return { ok: true, value: body };
}
