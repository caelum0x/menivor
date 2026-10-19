/**
 * Typed fetch client for the ReelForge ENTERPRISE Billing Platform endpoints
 * (Epic 3 — `app/controllers/v1/{subscriptions,usage,invoices}.py`). This is the
 * React Native / Expo mirror of the web `getSubscription` / `subscribeWorkspace` /
 * `getWorkspaceUsage` / `getEntitlements` / `listWorkspaceInvoices` / `getRevenue`
 * fetchers — same routes, same envelope handling, same integer-cent money shapes.
 *
 * Kept as a SEPARATE module from `lib/api.ts` on purpose (Billing is a
 * self-contained Enterprise feature). It reuses the shared primitives that
 * `lib/api.ts` already exports — `API_BASE`, `ApiError`, `isAbortError`,
 * `RequestOptions` — but owns a small request helper so it never has to touch
 * `lib/api.ts`.
 *
 * MONEY-CORRECTNESS / TENANT ISOLATION:
 *  - Every request is authorised as `x-api-key` (the signed-in caller's key). The
 *    backend gates the subscription/invoice management surface on `billing.manage`
 *    and the usage/entitlements reads on workspace membership, and scopes every
 *    read to ONE workspace — a caller can NEVER receive another tenant's rows.
 *  - `/admin/revenue` is served ONLY behind the platform `is_staff` gate.
 *  - All amounts are INTEGER minor units (cents) — never a float.
 *  - No secrets are hardcoded in this file. The subscription webhook is
 *    provider-driven (Stripe) and is intentionally absent here.
 */

import {
  API_BASE,
  ApiError,
  isAbortError,
  type RequestOptions,
} from "./api";
import type { ApiEnvelope } from "./types";

/** Public app-level API key (non-secret; shipped in the bundle by design). */
const APP_API_KEY: string = process.env.EXPO_PUBLIC_APP_API_KEY || "";

// ---------------------------------------------------------------------------
// §Billing shapes (mirror the controller's Pydantic models in schema.py)
// ---------------------------------------------------------------------------

/** Subscription lifecycle status. Only `active`/`trialing` grant the plan. */
export type SubscriptionStatus =
  | "active"
  | "past_due"
  | "canceled"
  | "trialing";

/** Billing cadence for a workspace subscription. */
export type SubscriptionInterval = "month" | "year";

/** The billing plan keys (mirror `app.services.entitlements.PLAN_ENTITLEMENTS`). */
export type PlanKey = "free" | "starter" | "pro" | "enterprise";

/**
 * A workspace's billing subscription (`SubscriptionModel`). Secret-free:
 * `provider_ref` is the provider-side id (e.g. the Stripe subscription id), never
 * a secret. `null` from {@link getSubscription} means the workspace has no
 * subscription (it then resolves to base/free entitlements).
 */
export interface Subscription {
  workspace_id: string;
  plan_key: string;
  provider: string;
  provider_ref: string;
  status: string;
  interval: string;
  seats: number;
  current_period_end: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Body for `POST /me/workspaces/{id}/subscribe` (`SubscribeRequest`). */
export interface SubscribeRequest {
  plan_key: string;
  interval?: SubscriptionInterval;
  seats?: number;
  /** Only the Stripe rail is supported for subscriptions. */
  provider?: "stripe";
}

/**
 * Hosted-checkout envelope returned by `subscribe`. Redirect the buyer to
 * `checkout_url`; credits/entitlements are granted only on webhook confirmation.
 */
export interface SubscribeResult {
  checkout_url: string;
  provider: string;
  plan_key: string;
  workspace_id: string | null;
}

/** Body for `POST /me/workspaces/{id}/change-plan` (`ChangePlanRequest`). */
export interface ChangePlanRequest {
  plan_key: string;
}

/**
 * The caller's active-plan entitlement bundle for a workspace
 * (`EntitlementsModel`). `entitlements` maps a feature key to its value (numeric
 * limits + boolean capabilities). A workspace with no live subscription -> `free`.
 */
export interface Entitlements {
  workspace_id: string;
  plan_key: string;
  entitlements: Record<string, number | boolean | string>;
}

/** Per-metric usage vs plan limit for a period (integer units). */
export interface MetricOverage {
  metric: string;
  used: number;
  /** `null` when the metric is unbounded for the plan. */
  limit: number | null;
  /** `max(0, used - limit)` — 0 when within allotment or unbounded. */
  overage: number;
}

/**
 * A workspace's metered usage + overage for a billing month (`UsageModel`).
 * Tenant-scoped: never another tenant's rows.
 */
export interface Usage {
  workspace_id: string;
  period: string;
  usage: Record<string, number>;
  overage: MetricOverage[];
}

/** One line on an invoice (integer minor-unit amount). */
export interface InvoiceLineItem {
  id: string;
  description: string;
  quantity: number;
  amount_cents: number;
  created_at: string | null;
}

/**
 * A workspace's invoice (`InvoiceModel`). `amount_cents` is the exact integer sum
 * of the lines in `currency` — never a float.
 */
export interface Invoice {
  id: string;
  workspace_id: string;
  provider_ref: string;
  amount_cents: number;
  currency: string;
  status: string;
  period_start: string | null;
  period_end: string | null;
  created_at: string | null;
  line_items: InvoiceLineItem[];
}

/**
 * Platform revenue summary (`RevenueModel`; `is_staff` ONLY). All amounts are
 * integer minor units (cents).
 */
export interface Revenue {
  revenue_cents: number;
  credits_granted: number;
  net_cents: number;
}

// ---------------------------------------------------------------------------
// Request helper (unwraps the { status, data, message } envelope) — a scoped
// copy of the shared `lib/api.ts` client so this module stays disjoint from it.
// ---------------------------------------------------------------------------

function buildHeaders(
  token: string | undefined,
  hasBody: boolean,
): Record<string, string> {
  const headers: Record<string, string> = {};
  const key = token || APP_API_KEY;
  if (key) headers["x-api-key"] = key;
  if (hasBody) headers["Content-Type"] = "application/json";
  return headers;
}

async function billingRequest<T>(
  path: string,
  init: {
    method?: string;
    body?: unknown;
    options?: RequestOptions;
  } = {},
): Promise<T> {
  const { method = "GET", body, options } = init;
  const hasBody = body !== undefined;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: buildHeaders(options?.token, hasBody),
      body: hasBody ? JSON.stringify(body) : undefined,
      signal: options?.signal,
    });
  } catch (err) {
    if (isAbortError(err)) throw err;
    throw new ApiError(
      `Network error contacting the API: ${
        err instanceof Error ? err.message : String(err)
      }`,
      0,
      err,
    );
  }

  let envelope: ApiEnvelope<T> | null = null;
  const raw = await res.text();
  if (raw) {
    try {
      envelope = JSON.parse(raw) as ApiEnvelope<T>;
    } catch {
      envelope = null;
    }
  }

  if (!res.ok) {
    const message =
      envelope?.message || `Request failed with status ${res.status}`.trim();
    throw new ApiError(message, res.status, envelope ?? raw);
  }

  if (envelope === null) {
    throw new ApiError(
      "Malformed response: expected a JSON envelope from the API.",
      res.status,
      raw,
    );
  }

  return (envelope.data ?? (envelope as unknown as T)) as T;
}

// ---------------------------------------------------------------------------
// Fetchers
// ---------------------------------------------------------------------------

/**
 * GET /me/workspaces/{id}/subscription — the workspace subscription, or `null`
 * when unset. Gated by `billing.manage` (403 for a caller without it).
 */
export function getSubscription(
  workspaceId: string,
  options?: RequestOptions,
): Promise<Subscription | null> {
  return billingRequest<Subscription | null>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/subscription`,
    { options },
  );
}

/**
 * POST /me/workspaces/{id}/subscribe — start a Stripe checkout; redirect the
 * buyer to `checkout_url`. No credits granted here (the webhook fulfils it
 * idempotently). Gated by `billing.manage`.
 */
export function subscribeWorkspace(
  workspaceId: string,
  body: SubscribeRequest,
  options?: RequestOptions,
): Promise<SubscribeResult> {
  return billingRequest<SubscribeResult>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/subscribe`,
    { method: "POST", body, options },
  );
}

/**
 * POST /me/workspaces/{id}/change-plan — switch the plan (DB-authoritative).
 * Returns the updated subscription. Gated by `billing.manage`.
 */
export function changeWorkspacePlan(
  workspaceId: string,
  body: ChangePlanRequest,
  options?: RequestOptions,
): Promise<Subscription> {
  return billingRequest<Subscription>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/change-plan`,
    { method: "POST", body, options },
  );
}

/**
 * POST /me/workspaces/{id}/cancel — cancel the subscription (entitlements fall
 * back to base/free). 404 when there is none. Gated by `billing.manage`.
 */
export function cancelWorkspaceSubscription(
  workspaceId: string,
  options?: RequestOptions,
): Promise<Subscription> {
  return billingRequest<Subscription>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/cancel`,
    { method: "POST", options },
  );
}

/**
 * GET /me/workspaces/{id}/entitlements — the caller's active-plan entitlement
 * bundle (base/free when no live sub). Tenant-scoped: any member may read it.
 */
export function getEntitlements(
  workspaceId: string,
  options?: RequestOptions,
): Promise<Entitlements> {
  return billingRequest<Entitlements>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/entitlements`,
    { options },
  );
}

/**
 * GET /me/workspaces/{id}/usage?period=YYYY-MM — metered usage + overage for a
 * billing month (defaults to the current month). Tenant-scoped: any member reads.
 */
export function getWorkspaceUsage(
  workspaceId: string,
  period?: string,
  options?: RequestOptions,
): Promise<Usage> {
  const query = period ? `?period=${encodeURIComponent(period)}` : "";
  return billingRequest<Usage>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/usage${query}`,
    { options },
  );
}

/**
 * GET /me/workspaces/{id}/invoices — the workspace's invoices (newest first),
 * TENANT-SCOPED. Normalizes both an array and a `{ invoices: [...] }` wrapper.
 * Gated by `billing.manage`.
 */
export async function listWorkspaceInvoices(
  workspaceId: string,
  options?: RequestOptions,
): Promise<Invoice[]> {
  const data = await billingRequest<Invoice[] | { invoices?: Invoice[] }>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/invoices`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.invoices ?? [];
}

/**
 * GET /admin/revenue — the platform-wide revenue summary (integer cents).
 * HARD-GATED on `is_staff`; a non-staff caller gets 403.
 */
export function getRevenue(options?: RequestOptions): Promise<Revenue> {
  return billingRequest<Revenue>("/admin/revenue", { options });
}
