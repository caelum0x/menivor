/**
 * Typed fetch client for the ReelForge ENTERPRISE Compliance endpoints
 * (Epic 5 — `app/controllers/v1/compliance.py`). This is the React Native /
 * Expo surface for GDPR self-service: EXPORT all of my data (Art. 15 / 20),
 * ERASE my account (Art. 17), and record CONSENT decisions.
 *
 * Kept as a SEPARATE module from `lib/api.ts` (same pattern as `lib/developer.ts`
 * and `lib/sso.ts` — a self-contained Enterprise feature). It reuses the shared
 * primitives `lib/api.ts` already exports (`API_BASE`, `ApiError`, `isAbortError`,
 * `RequestOptions`) but owns a small request helper so it never has to touch
 * `lib/api.ts`.
 *
 * SECURITY / SCOPING:
 *  - Every route is authorised as `x-api-key` (the signed-in caller) and is
 *    STRICTLY caller-scoped server-side: the export archive and the erasure both
 *    contain / affect ONLY the requesting caller's own data. No path accepts a
 *    target user id, so a caller can never export or erase another account.
 *  - The export `download_url` is a SHORT-LIVED presigned R2 GET link (never a
 *    public URL); it is opened once and never persisted here.
 *  - Erasure is irreversible and requires an explicit `confirm=true` step — a
 *    missing/false confirmation is a 400 {@link ApiError} and nothing is erased.
 *    It also revokes every API key server-side, so the caller must be signed out
 *    afterwards.
 *  - Consent is append-only and always recorded for the CALLER.
 *  - No secrets are hardcoded in this file.
 */

import { API_BASE, ApiError, isAbortError, type RequestOptions } from "./api";
import type { ApiEnvelope } from "./types";

/** Public app-level API key (non-secret; shipped in the bundle by design). */
const APP_API_KEY: string = process.env.EXPO_PUBLIC_APP_API_KEY || "";

/**
 * The policy version recorded against a consent decision made from this build.
 * Bumping it when the privacy policy changes lets the audit trail distinguish
 * decisions made under different policy versions.
 */
export const CONSENT_POLICY_VERSION = "1";

// ---------------------------------------------------------------------------
// §Shapes (mirror the Pydantic models in app/models/schema.py)
// ---------------------------------------------------------------------------

/**
 * The result of a self-service data export (`DataExportModel`). `download_url`
 * is a SHORT-LIVED presigned GET link to the caller's private export archive;
 * `expires_in` is its lifetime in seconds. The archive holds ONLY the caller's
 * own data.
 */
export interface DataExport {
  /** Short-lived presigned R2 GET link to the caller's export archive. */
  download_url: string;
  /** Lifetime of the link, in seconds. */
  expires_in: number;
}

/**
 * A right-to-erasure request's public shape (`ErasureRequestModel`). `status`
 * moves `requested -> processing -> completed`. Erasure ANONYMIZES PII in place
 * (email/name/handle tombstoned, credentials revoked) while PRESERVING
 * legally-required financial / audit records; it never cascade-deletes.
 */
export interface ErasureRequest {
  /** The erasure request id. */
  id: string;
  /** The user this erasure applies to (always the caller). */
  user_id: string;
  /** Lifecycle status: `requested` | `processing` | `completed`. */
  status: string;
  /** What was erased (e.g. `"user"`). */
  scope: string;
  /** ISO-8601 timestamp the erasure was requested, when available. */
  requested_at: string | null;
  /** ISO-8601 timestamp the erasure completed, when available. */
  completed_at: string | null;
}

/**
 * One append-only consent decision (`ConsentRecordModel`). Records that the
 * caller GRANTED or withdrew consent for a `kind` at a policy `version`.
 */
export interface ConsentRecord {
  /** The record id, when the backend assigns one. */
  id: number | null;
  /** The consent dimension, e.g. `"marketing"`. */
  kind: string;
  /** Whether consent is currently granted. */
  granted: boolean;
  /** The policy version the decision was made against. */
  version: string;
  /** ISO-8601 creation timestamp, when available. */
  created_at: string | null;
}

/**
 * A workspace's data-retention policy (`RetentionPolicyModel`). Two independent
 * windows bound how long a workspace's members' JOBS and ASSETS are kept before
 * the periodic sweep anonymizes the aged rows. `null` on a dimension means KEEP
 * FOREVER (that dimension is never swept). Reading/writing is gated server-side
 * on the `workspace.settings` permission (owner/admin); a viewer/non-member is
 * refused with a 403 and never learns another tenant's posture.
 */
export interface RetentionPolicy {
  /** The workspace the policy belongs to. */
  workspace_id: string;
  /** Days jobs are kept before the sweep anonymizes them; `null` = keep forever. */
  jobs_retention_days: number | null;
  /** Days assets are kept before the sweep anonymizes them; `null` = keep forever. */
  assets_retention_days: number | null;
  /** ISO-8601 timestamp the policy was first created, when configured. */
  created_at: string | null;
  /** ISO-8601 timestamp of the last change, when configured. */
  updated_at: string | null;
}

/**
 * Body for {@link setRetentionPolicy} — a FULL REPLACE of both windows.
 * `null` (or omitted) on a dimension means keep-forever; a value must be a
 * non-negative integer (the backend rejects a negative with a 400).
 */
export interface RetentionPolicyUpdate {
  jobs_retention_days: number | null;
  assets_retention_days: number | null;
}

/** A user-facing consent dimension rendered as a toggle on the Privacy screen. */
export interface ConsentKind {
  /** The `kind` sent to / read from the API. */
  kind: string;
  /** Short human label for the toggle row. */
  label: string;
  /** One-line explanation of what granting this consent means. */
  description: string;
  /** Whether this consent is OFF by default until the caller opts in. */
  defaultGranted: boolean;
}

/**
 * The curated set of consent dimensions surfaced as toggles. The API accepts any
 * `kind` string (it re-validates and audits every write), but the app only shows
 * these opt-in dimensions; `tos` and other attestations are captured elsewhere.
 * All default OFF — consent is opt-in, never assumed.
 */
export const CONSENT_KINDS: readonly ConsentKind[] = [
  {
    kind: "marketing",
    label: "Marketing emails",
    description: "Product news, tips and occasional offers.",
    defaultGranted: false,
  },
  {
    kind: "analytics",
    label: "Product analytics",
    description: "Allow anonymous usage analytics to help improve the app.",
    defaultGranted: false,
  },
  {
    kind: "ai_disclosure",
    label: "AI personalization",
    description: "Use your reels to personalize AI hook and idea suggestions.",
    defaultGranted: false,
  },
] as const;

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

async function complianceRequest<T>(
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
// degrade to safe defaults rather than crash the Privacy screen).
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

function normalizeExport(value: unknown): DataExport {
  const row =
    value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    download_url: str(row.download_url),
    expires_in: nonNegInt(row.expires_in),
  };
}

function normalizeErasure(value: unknown): ErasureRequest {
  const row =
    value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    id: str(row.id),
    user_id: str(row.user_id),
    status: str(row.status, "requested"),
    scope: str(row.scope, "user"),
    requested_at: nullableStr(row.requested_at),
    completed_at: nullableStr(row.completed_at),
  };
}

/** Coerce an unknown row into a {@link ConsentRecord}, or `null` when malformed. */
function normalizeConsent(value: unknown): ConsentRecord | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const kind = str(row.kind);
  if (!kind) return null;
  return {
    id:
      typeof row.id === "number" && Number.isFinite(row.id)
        ? Math.trunc(row.id)
        : null,
    kind,
    granted: row.granted === true,
    version: str(row.version),
    created_at: nullableStr(row.created_at),
  };
}

/**
 * Reduce a consent trail (oldest-first, per the API) to the CURRENT decision for
 * each `kind` — the newest row for a `kind` wins. Used to seed the toggle states.
 */
export function latestConsents(
  trail: readonly ConsentRecord[],
): Record<string, boolean> {
  const current: Record<string, boolean> = {};
  for (const record of trail) {
    // The trail is oldest-first, so a later row overwrites an earlier decision.
    current[record.kind] = record.granted;
  }
  return current;
}

// ---------------------------------------------------------------------------
// Data export (GDPR Art. 15 / 20) — strictly caller-scoped
// ---------------------------------------------------------------------------

/**
 * POST /me/data-export — assemble the caller's COMPLETE data package, upload it
 * to R2 under an owner-scoped key, and return a SHORT-LIVED presigned download
 * link. Strictly caller-scoped; audited server-side. Never returns another
 * user's data.
 */
export async function requestDataExport(
  options?: RequestOptions,
): Promise<DataExport> {
  const data = await complianceRequest<unknown>("/me/data-export", {
    method: "POST",
    options,
  });
  return normalizeExport(data);
}

// ---------------------------------------------------------------------------
// Right to erasure (GDPR Art. 17) — the caller's OWN account only
// ---------------------------------------------------------------------------

/**
 * POST /me/erase — anonymize the CALLER'S OWN account (irreversible). Requires an
 * explicit `confirm=true` (sent here); the backend rejects a missing/false
 * confirmation with a 400 {@link ApiError}. On success the caller's PII is
 * tombstoned and EVERY API key is revoked, so the caller must be signed out
 * afterwards. No target id is accepted — a caller can only ever erase themselves.
 */
export async function eraseAccount(
  options?: RequestOptions,
): Promise<ErasureRequest> {
  const data = await complianceRequest<unknown>("/me/erase", {
    method: "POST",
    body: { confirm: true },
    options,
  });
  return normalizeErasure(data);
}

// ---------------------------------------------------------------------------
// Consent (GDPR / SOC2) — caller-scoped, append-only
// ---------------------------------------------------------------------------

/**
 * GET /me/consent — the caller's full consent trail (oldest-first). Malformed
 * rows are dropped. Use {@link latestConsents} to derive the current per-`kind`
 * decision for the toggles.
 */
export async function getConsentTrail(
  options?: RequestOptions,
): Promise<ConsentRecord[]> {
  const data = await complianceRequest<unknown>("/me/consent", { options });
  const rows = Array.isArray(data) ? data : [];
  return rows
    .map(normalizeConsent)
    .filter((c): c is ConsentRecord => c !== null);
}

/**
 * PUT /me/consent — append an immutable consent decision for the caller (always
 * scoped to the caller, never another user). `version` defaults to the current
 * {@link CONSENT_POLICY_VERSION}. Returns the recorded decision.
 */
export async function recordConsent(
  kind: string,
  granted: boolean,
  options?: RequestOptions & { version?: string },
): Promise<ConsentRecord> {
  const { version, ...reqOptions } = options ?? {};
  const data = await complianceRequest<unknown>("/me/consent", {
    method: "PUT",
    body: {
      kind,
      granted,
      version: version ?? CONSENT_POLICY_VERSION,
    },
    options: reqOptions,
  });
  const record = normalizeConsent(data);
  if (record === null) {
    throw new ApiError(
      "Malformed response: expected a consent record from the API.",
      200,
      data,
    );
  }
  return record;
}

// ---------------------------------------------------------------------------
// Retention policy (RBAC `workspace.settings`) — tenant-scoped, audited
// ---------------------------------------------------------------------------

/** Coerce a raw retention window into a non-negative integer or `null`. */
function retentionDays(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.max(0, Math.trunc(value));
}

/** Coerce an unknown payload into a well-formed {@link RetentionPolicy}. */
function normalizeRetentionPolicy(
  workspaceId: string,
  value: unknown,
): RetentionPolicy {
  const row =
    value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    workspace_id: str(row.workspace_id, workspaceId),
    jobs_retention_days: retentionDays(row.jobs_retention_days),
    assets_retention_days: retentionDays(row.assets_retention_days),
    created_at: nullableStr(row.created_at),
    updated_at: nullableStr(row.updated_at),
  };
}

/**
 * GET /me/workspaces/{workspace_id}/retention — read a workspace's data-retention
 * policy. Gated server-side on `workspace.settings`: a viewer / non-member gets a
 * 403 ({@link ApiError}) and never learns another tenant's posture, and an unknown
 * workspace a 404. When no policy is configured yet the backend returns a
 * keep-forever default (both windows `null`). Strictly tenant-scoped.
 */
export async function getRetentionPolicy(
  workspaceId: string,
  options?: RequestOptions,
): Promise<RetentionPolicy> {
  const data = await complianceRequest<unknown>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/retention`,
    { options },
  );
  return normalizeRetentionPolicy(workspaceId, data);
}

/**
 * PUT /me/workspaces/{workspace_id}/retention — set a workspace's retention
 * window (a FULL REPLACE of both dimensions; audited server-side). `null` on a
 * dimension means keep-forever; a value must be a non-negative integer. Gated on
 * `workspace.settings`: an owner/admin may set it, a viewer / non-member is
 * refused with a 403 BEFORE any write. A negative value is a 400 and an unknown
 * workspace a 404 ({@link ApiError}). Returns the updated policy.
 */
export async function setRetentionPolicy(
  workspaceId: string,
  body: Readonly<RetentionPolicyUpdate>,
  options?: RequestOptions,
): Promise<RetentionPolicy> {
  const data = await complianceRequest<unknown>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/retention`,
    {
      method: "PUT",
      body: {
        jobs_retention_days: body.jobs_retention_days,
        assets_retention_days: body.assets_retention_days,
      },
      options,
    },
  );
  return normalizeRetentionPolicy(workspaceId, data);
}
