/**
 * Typed fetch client for the ReelForge ENTERPRISE API Platform endpoints
 * (Epic 4 — `app/controllers/v1/developer.py` + `app/controllers/v1/webhooks_admin.py`).
 * This is the React Native / Expo mirror of the web developer-portal + webhook
 * fetchers — same routes, same envelope handling, same SECRET-FREE shapes.
 *
 * Kept as a SEPARATE module from `lib/api.ts` on purpose (the developer / API
 * platform surface is a self-contained Enterprise feature — same pattern as
 * `lib/sso.ts`). It reuses the shared primitives `lib/api.ts` already exports
 * (`API_BASE`, `ApiError`, `isAbortError`, `RequestOptions`) but owns a small
 * request helper so it never has to touch `lib/api.ts`.
 *
 * SECURITY / TENANT ISOLATION:
 *  - Every request is authorised as `x-api-key` (the signed-in owner/admin key);
 *    the webhook management routes are gated server-side on the
 *    `workspace.settings` permission and scoped to ONE workspace. A foreign /
 *    unknown subscription is a 404 — another tenant's rows never leak.
 *  - A webhook subscription's HMAC signing `secret` is returned by the API
 *    EXACTLY ONCE, in the create response ({@link CreatedWebhookSubscription}).
 *    Every list/get/delivery view is secret-free ({@link WebhookSubscription}).
 *    The one-time secret is held only in the calling screen's ephemeral state and
 *    is never persisted here.
 *  - The callback `url` is SSRF-validated server-side (the SAME guard the delivery
 *    primitive uses) BEFORE any row is persisted; a loopback / private / link-local
 *    / metadata target surfaces here as a 400 {@link ApiError}. The client never
 *    weakens that guard.
 *  - No secrets are hardcoded in this file.
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

/**
 * The catalog of webhook event types a subscription may listen for. Mirrors
 * `WEBHOOK_EVENT_TYPES` in `app/models/schema.py`. Kept as a `const` tuple so the
 * create form can render the exact supported set; the API is still the source of
 * truth (the portal summary returns its own `webhook_event_types`, preferred when
 * present) and re-validates every request.
 */
export const WEBHOOK_EVENT_TYPES = [
  "job.completed",
  "publish.succeeded",
  "publish.failed",
  "performance.ingested",
] as const;

export type WebhookEventType = (typeof WEBHOOK_EVENT_TYPES)[number];

// ---------------------------------------------------------------------------
// §Shapes (mirror the controllers' Pydantic models in app/models/schema.py)
// ---------------------------------------------------------------------------

/** The caller's API-key footprint (`DeveloperApiKeysSummaryModel`) — counts only. */
export interface DeveloperApiKeysSummary {
  /** Total number of the caller's personal API keys. */
  total: number;
  /** How many of those keys are still active (not revoked). */
  active: number;
  /** The calendar month `requests_this_month` is measured over (`"YYYY-MM"`). */
  period_ym: string;
  /** Sum of this month's request usage across all the caller's keys. */
  requests_this_month: number;
}

/** The caller's webhook-subscription footprint (`DeveloperWebhooksSummaryModel`). */
export interface DeveloperWebhooksSummary {
  /** Total subscriptions across every workspace the caller belongs to. */
  total: number;
  /** How many of those subscriptions are enabled. */
  active: number;
  /** The supported event catalog, per the API. */
  event_types: string[];
}

/**
 * The caller-scoped developer portal summary (`DeveloperPortalModel`) — a
 * READ-only footprint plus static integration metadata. Never carries a secret.
 */
export interface DeveloperPortal {
  api_keys: DeveloperApiKeysSummary;
  webhooks: DeveloperWebhooksSummary;
  /** Number of workspaces the caller belongs to. */
  workspaces: number;
  /** The API base (origin + `/api/v1`). */
  api_base_url: string;
  /** The OpenAPI schema URL. */
  openapi_url: string;
  /** The interactive docs URL. */
  docs_url: string;
  /** The API version string, when the server reports one. */
  api_version: string;
  /** The supported webhook event catalog (source of truth for the create form). */
  webhook_event_types: string[];
}

/**
 * A webhook subscription in its public, SECRET-FREE envelope
 * (`WebhookSubscriptionModel`). NEVER carries the signing secret — only the id,
 * owning workspace, callback url, subscribed events, the `enabled` kill-switch,
 * and lifecycle timestamps.
 */
export interface WebhookSubscription {
  /** Subscription id — the path param for revoke / test / deliveries. */
  id: string;
  /** The workspace this subscription belongs to (tenant scope). */
  workspace_id: string;
  /** The customer callback URL deliveries are POSTed to. */
  url: string;
  /** The event types this subscription receives. */
  event_types: string[];
  /** Whether deliveries are currently enabled for this subscription. */
  enabled: boolean;
  /** ISO-8601 creation timestamp, when available. */
  created_at: string | null;
  /** ISO-8601 last-update timestamp, when available. */
  updated_at: string | null;
}

/**
 * The ONE-TIME reveal returned by {@link createWebhookSubscription}
 * (`WebhookSubscriptionCreatedModel`). SECURITY: `secret` is the subscription's
 * HMAC signing key and is present ONLY here, exactly once — the server keeps only
 * an encrypted blob, so a lost secret means the subscription must be re-created.
 */
export interface CreatedWebhookSubscription extends WebhookSubscription {
  /** The HMAC signing secret — shown ONCE and unrecoverable. */
  secret: string;
}

/** Body for {@link createWebhookSubscription} (`WebhookSubscribeRequest`). */
export interface WebhookSubscribeRequest {
  /** Customer callback URL (https). SSRF-validated server-side. */
  url: string;
  /** Event types to receive; must be a subset of the supported catalog. */
  event_types: string[];
}

/**
 * One delivery attempt-record of an event to a subscription (`WebhookDeliveryModel`)
 * — SECRET-FREE and payload-free. `status` is `pending | delivered | failed`;
 * `attempts` / `last_attempt_at` / `response_code` reflect the capped-backoff retry
 * state. The signed payload body is intentionally omitted.
 */
export interface WebhookDelivery {
  /** The delivery id (a unique id per event, used for idempotent dedupe). */
  id: string;
  /** The subscription this delivery belongs to. */
  subscription_id: string;
  /** The event type delivered, e.g. `"job.completed"` or `"webhook.test"`. */
  event_type: string;
  /** The event id (stable across retries of the same event). */
  event_id: string;
  /** Delivery status: `pending` | `delivered` | `failed` (widened for forward-compat). */
  status: string;
  /** Number of delivery attempts made so far. */
  attempts: number;
  /** ISO-8601 timestamp of the last attempt, when available. */
  last_attempt_at: string | null;
  /** The HTTP status code of the last attempt, when the endpoint responded. */
  response_code: number | null;
  /** ISO-8601 creation timestamp, when available. */
  created_at: string | null;
}

/** Acknowledgement returned by {@link deleteWebhookSubscription}. */
export interface WebhookRevokeResult {
  revoked: boolean;
  subscription_id: string;
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

async function devRequest<T>(
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
    // Network-level failure (DNS, offline, aborted).
    if (isAbortError(err)) throw err;
    throw new ApiError(
      `Network error contacting the API: ${
        err instanceof Error ? err.message : String(err)
      }`,
      0,
      err,
    );
  }

  // Parse the envelope defensively — error responses may not be JSON.
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
// Defensive normalisation (the API is trusted, but a partial/legacy row should
// degrade to safe defaults rather than crash a status screen).
// ---------------------------------------------------------------------------

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function nullableStr(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function nonNegInt(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, Math.trunc(value))
    : 0;
}

function nullableInt(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.trunc(value)
    : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string" && v.length > 0)
    : [];
}

function normalizePortal(value: unknown): DeveloperPortal {
  const row =
    value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  const keys =
    row.api_keys && typeof row.api_keys === "object"
      ? (row.api_keys as Record<string, unknown>)
      : {};
  const hooks =
    row.webhooks && typeof row.webhooks === "object"
      ? (row.webhooks as Record<string, unknown>)
      : {};
  const catalog = stringList(row.webhook_event_types);
  return {
    api_keys: {
      total: nonNegInt(keys.total),
      active: nonNegInt(keys.active),
      period_ym: str(keys.period_ym),
      requests_this_month: nonNegInt(keys.requests_this_month),
    },
    webhooks: {
      total: nonNegInt(hooks.total),
      active: nonNegInt(hooks.active),
      event_types: stringList(hooks.event_types),
    },
    workspaces: nonNegInt(row.workspaces),
    api_base_url: str(row.api_base_url),
    openapi_url: str(row.openapi_url),
    docs_url: str(row.docs_url),
    api_version: str(row.api_version),
    webhook_event_types:
      catalog.length > 0 ? catalog : [...WEBHOOK_EVENT_TYPES],
  };
}

/** Coerce an unknown row into a {@link WebhookSubscription}, or `null` when malformed. */
function normalizeSubscription(value: unknown): WebhookSubscription | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const id = str(row.id);
  if (!id) return null;
  return {
    id,
    workspace_id: str(row.workspace_id),
    url: str(row.url),
    event_types: stringList(row.event_types),
    enabled: row.enabled === true,
    created_at: nullableStr(row.created_at),
    updated_at: nullableStr(row.updated_at),
  };
}

/** Coerce the create response into a {@link CreatedWebhookSubscription}, or `null`. */
function normalizeCreated(value: unknown): CreatedWebhookSubscription | null {
  const base = normalizeSubscription(value);
  if (base === null) return null;
  const row = value as Record<string, unknown>;
  return { ...base, secret: str(row.secret) };
}

/** Coerce an unknown row into a {@link WebhookDelivery}, or `null` when malformed. */
function normalizeDelivery(value: unknown): WebhookDelivery | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const id = str(row.id);
  if (!id) return null;
  return {
    id,
    subscription_id: str(row.subscription_id),
    event_type: str(row.event_type),
    event_id: str(row.event_id),
    status: str(row.status, "pending"),
    attempts: nonNegInt(row.attempts),
    last_attempt_at: nullableStr(row.last_attempt_at),
    response_code: nullableInt(row.response_code),
    created_at: nullableStr(row.created_at),
  };
}

// ---------------------------------------------------------------------------
// Developer portal (caller-scoped, read-only)
// ---------------------------------------------------------------------------

/**
 * GET /me/developer — the caller-scoped developer portal summary: their API-key
 * footprint (counts + current-month request usage), their webhook-subscription
 * footprint across the workspaces they belong to, the number of workspaces, and
 * static integration links. READ-only and SECRET-FREE.
 */
export async function getDeveloperPortal(
  options?: RequestOptions,
): Promise<DeveloperPortal> {
  const data = await devRequest<unknown>("/me/developer", { options });
  return normalizePortal(data);
}

// ---------------------------------------------------------------------------
// Webhook subscriptions (owner/admin — RBAC `workspace.settings`, tenant-scoped)
// ---------------------------------------------------------------------------

/**
 * POST /me/workspaces/{id}/webhooks — register a subscription and return the HMAC
 * signing `secret` EXACTLY ONCE (only an encrypted blob is persisted). Gated by
 * `workspace.settings`. The `url` is SSRF-validated server-side BEFORE any row is
 * persisted (a loopback / private / link-local / metadata target is a 400
 * {@link ApiError}); an unknown event type is likewise a 400.
 */
export async function createWebhookSubscription(
  workspaceId: string,
  body: WebhookSubscribeRequest,
  options?: RequestOptions,
): Promise<CreatedWebhookSubscription> {
  const data = await devRequest<unknown>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/webhooks`,
    { method: "POST", body, options },
  );
  const created = normalizeCreated(data);
  if (created === null) {
    throw new ApiError(
      "Malformed response: expected a created webhook subscription from the API.",
      200,
      data,
    );
  }
  return created;
}

/**
 * GET /me/workspaces/{id}/webhooks — the workspace's subscriptions (newest first),
 * SECRET-FREE. Gated by `workspace.settings`; tenant-scoped, so a caller only ever
 * sees their own workspace's subscriptions. Malformed rows are dropped.
 */
export async function listWebhookSubscriptions(
  workspaceId: string,
  options?: RequestOptions,
): Promise<WebhookSubscription[]> {
  const data = await devRequest<unknown>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/webhooks`,
    { options },
  );
  const rows = Array.isArray(data) ? data : [];
  return rows
    .map(normalizeSubscription)
    .filter((s): s is WebhookSubscription => s !== null);
}

/**
 * DELETE /me/workspaces/{id}/webhooks/{subId} — soft-revoke a subscription.
 * Gated by `workspace.settings` and tenant-scoped: a foreign / unknown id is a 404
 * {@link ApiError}. The revoke is audited server-side.
 */
export async function deleteWebhookSubscription(
  workspaceId: string,
  subscriptionId: string,
  options?: RequestOptions,
): Promise<WebhookRevokeResult> {
  const data = await devRequest<Record<string, unknown>>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/webhooks/${encodeURIComponent(
      subscriptionId,
    )}`,
    { method: "DELETE", options },
  );
  return {
    revoked: data?.revoked === true,
    subscription_id: str(data?.id, subscriptionId),
  };
}

/**
 * POST /me/workspaces/{id}/webhooks/{subId}/test — send a signed test event to the
 * subscription's URL via the EXISTING SSRF-guarded, HMAC-signing delivery
 * primitive, and return the resulting {@link WebhookDelivery} record. Gated by
 * `workspace.settings`; a foreign / unknown subscription is a 404 {@link ApiError}.
 */
export async function testWebhookSubscription(
  workspaceId: string,
  subscriptionId: string,
  options?: RequestOptions,
): Promise<WebhookDelivery> {
  const data = await devRequest<unknown>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/webhooks/${encodeURIComponent(
      subscriptionId,
    )}/test`,
    { method: "POST", options },
  );
  const delivery = normalizeDelivery(data);
  if (delivery === null) {
    throw new ApiError(
      "Malformed response: expected a delivery record from the API.",
      200,
      data,
    );
  }
  return delivery;
}

/**
 * GET /me/workspaces/{id}/webhooks/{subId}/deliveries — a subscription's recent
 * deliveries (newest first) with their status. Gated by `workspace.settings`;
 * tenant-scoped, so a foreign / unknown subscription is a 404 {@link ApiError} and
 * another tenant's deliveries never leak. The signed payload body is omitted.
 * `limit` is clamped to the API's `[1, 100]` window.
 */
export async function listWebhookDeliveries(
  workspaceId: string,
  subscriptionId: string,
  limit = 50,
  options?: RequestOptions,
): Promise<WebhookDelivery[]> {
  const safeLimit = Math.min(100, Math.max(1, Math.trunc(limit) || 50));
  const data = await devRequest<unknown>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/webhooks/${encodeURIComponent(
      subscriptionId,
    )}/deliveries?limit=${safeLimit}`,
    { options },
  );
  const rows = Array.isArray(data) ? data : [];
  return rows
    .map(normalizeDelivery)
    .filter((d): d is WebhookDelivery => d !== null);
}
