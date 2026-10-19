/**
 * Typed fetch client for the ReelForge ENTERPRISE Identity & SSO endpoints
 * (Epic 2 — `app/controllers/v1/sso.py`, `security_policy.py`, `scim.py`). This is
 * the React Native / Expo mirror of the web `use-sso-connection` /
 * `use-security-policy` / `use-scim-tokens` fetchers — same routes, same envelope
 * handling, same cert-free shapes.
 *
 * Kept as a SEPARATE module from `lib/api.ts` on purpose (SSO is a self-contained
 * Enterprise feature). It reuses the shared primitives that `lib/api.ts` already
 * exports — `API_BASE`, `ApiError`, `isAbortError`, `RequestOptions` — but owns a
 * small request helper so it never has to touch `lib/api.ts`.
 *
 * SECURITY / TENANT ISOLATION:
 *  - Every request is authorised as `x-api-key` (the signed-in owner/admin key);
 *    the backend gates all of these on the `workspace.settings` permission and
 *    scopes each connection / token / policy to ONE workspace.
 *  - The IdP signing certificate and OIDC client secret are NEVER returned by the
 *    API and are NEVER entered on mobile — only the `has_certificate` /
 *    `has_client_secret` booleans report whether a secret is configured. A raw
 *    SCIM token is present EXACTLY ONCE, in the mint response, and is never
 *    persisted here beyond the calling screen's ephemeral state.
 *  - No secrets are hardcoded in this file.
 *
 * The IdP-facing surfaces (`GET/POST /sso/{id}/{login,acs,metadata}` and the SCIM
 * 2.0 provisioning endpoints) are called by the identity provider / browser, not
 * by the app clients, so they are intentionally absent here.
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
// §SSO shapes (mirror the controller's Pydantic models in app/models/schema.py)
// ---------------------------------------------------------------------------

/**
 * The CERT-FREE public view of a workspace's Enterprise SSO connection
 * (`SSOConnectionModel`). The IdP signing certificate and OIDC client secret are
 * never carried — only `has_certificate` / `has_client_secret` report whether a
 * secret is configured. `protocol` is widened to `string` for forward-compat.
 */
export interface SsoConnection {
  /** The workspace this connection belongs to (tenant scope). */
  workspace_id: string;
  /** Identity protocol: `"saml"` | `"oidc"` (widened for forward-compat). */
  protocol: string;
  /** IdP entity id (SAML issuer). */
  idp_entity_id: string;
  /** IdP single-sign-on URL the browser is redirected to. */
  idp_sso_url: string;
  /** SP assertion-consumer-service URL (where the IdP posts the assertion). */
  sp_acs_url: string;
  /** SP metadata URL an admin hands to the IdP. */
  sp_metadata_url: string;
  /** OIDC client id, when the protocol is `oidc` (else `null`). */
  oidc_client_id: string | null;
  /** Whether SSO login is currently enabled for this workspace. */
  enabled: boolean;
  /** True when an IdP signing certificate is stored (the cert itself is never returned). */
  has_certificate: boolean;
  /** True when an OIDC client secret is stored (the secret itself is never returned). */
  has_client_secret: boolean;
  /** ISO-8601 creation timestamp, when available. */
  created_at: string | null;
  /** ISO-8601 last-update timestamp, when available. */
  updated_at: string | null;
}

/**
 * Body for `PUT /me/workspaces/{id}/sso` (`SSOConfigRequest`). `idp_x509_cert` and
 * `oidc_client_secret` are WRITE-ONLY and Fernet-encrypted server-side — they are
 * never entered on mobile (no cert entry), so they are optional here and omitting
 * them re-saves the connection WITHOUT a stored secret. `protocol` must be
 * `"saml"` | `"oidc"`.
 */
export interface SsoConfigRequest {
  protocol?: string;
  idp_entity_id?: string;
  idp_sso_url?: string;
  /** Write-only IdP signing cert; never entered on mobile. */
  idp_x509_cert?: string;
  sp_acs_url?: string;
  oidc_client_id?: string;
  /** Write-only OIDC client secret; never entered on mobile. */
  oidc_client_secret?: string;
  enabled?: boolean;
}

/**
 * A workspace's enterprise login security policy (`SecurityPolicyModel`) —
 * cert-free, no secrets. All lists default to `[]` and numeric/boolean rules to a
 * safe "off" default so a partial/legacy payload degrades instead of throwing.
 */
export interface SecurityPolicy {
  /** The workspace this policy governs (tenant scope). */
  workspace_id: string;
  /** When true, members must sign in through the configured IdP. */
  require_sso: boolean;
  /** Idle session timeout in minutes (0 = no enforced timeout). */
  session_timeout_min: number;
  /** Email domains permitted to sign in (empty = no restriction). */
  allowed_email_domains: string[];
  /** When true, members must complete MFA. */
  mfa_required: boolean;
  /** CIDRs / IPs permitted to sign in (empty = no restriction). */
  ip_allowlist: string[];
  /** ISO-8601 creation timestamp, when available. */
  created_at: string | null;
  /** ISO-8601 last-update timestamp, when available. */
  updated_at: string | null;
}

/**
 * Body for `PUT /me/workspaces/{id}/security` (`SecurityPolicyRequest`) — a
 * PARTIAL update. Only supplied (non-`undefined`) fields are applied, so a caller
 * can toggle a single rule without resending the whole policy.
 */
export interface SecurityPolicyRequest {
  require_sso?: boolean;
  session_timeout_min?: number;
  allowed_email_domains?: string[];
  mfa_required?: boolean;
  ip_allowlist?: string[];
}

/**
 * A workspace's SCIM bearer-token descriptor (`ScimTokenModel`). The raw `token`
 * is populated ONLY by {@link createScimToken} (shown once, then unrecoverable); a
 * listing carries `token: null` and only the non-secret `prefix`.
 */
export interface ScimToken {
  /** Token id — the path param for revocation. */
  id: string;
  /** The workspace the token provisions into (tenant scope). */
  workspace_id: string;
  /** Non-secret display prefix of the token. */
  prefix: string;
  /** The raw bearer token — present ONLY in the mint response, else `null`. */
  token: string | null;
  /** Whether the token has been revoked. */
  revoked: boolean;
  /** ISO-8601 last-used timestamp, when available. */
  last_used_at: string | null;
  /** ISO-8601 creation timestamp, when available. */
  created_at: string | null;
}

/** Acknowledgement returned by {@link deleteSsoConnection}. */
export interface SsoDeleteResult {
  deleted: boolean;
  workspace_id: string;
}

/** Acknowledgement returned by {@link revokeScimToken}. */
export interface ScimTokenRevokeResult {
  revoked: boolean;
  token_id: string;
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

async function ssoRequest<T>(
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

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];
}

/** Coerce an unknown payload into a {@link SsoConnection}, or `null` when unset. */
function normalizeConnection(value: unknown): SsoConnection | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const workspace_id = str(row.workspace_id);
  if (!workspace_id) return null;
  return {
    workspace_id,
    protocol: str(row.protocol, "saml"),
    idp_entity_id: str(row.idp_entity_id),
    idp_sso_url: str(row.idp_sso_url),
    sp_acs_url: str(row.sp_acs_url),
    sp_metadata_url: str(row.sp_metadata_url),
    oidc_client_id: nullableStr(row.oidc_client_id),
    enabled: row.enabled === true,
    has_certificate: row.has_certificate === true,
    has_client_secret: row.has_client_secret === true,
    created_at: nullableStr(row.created_at),
    updated_at: nullableStr(row.updated_at),
  };
}

/** Coerce an unknown payload into a {@link SecurityPolicy}, or `null` when unset. */
function normalizePolicy(value: unknown): SecurityPolicy | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const workspace_id = str(row.workspace_id);
  if (!workspace_id) return null;
  const timeout = row.session_timeout_min;
  return {
    workspace_id,
    require_sso: row.require_sso === true,
    session_timeout_min:
      typeof timeout === "number" && Number.isFinite(timeout)
        ? Math.max(0, Math.trunc(timeout))
        : 0,
    allowed_email_domains: stringList(row.allowed_email_domains),
    mfa_required: row.mfa_required === true,
    ip_allowlist: stringList(row.ip_allowlist),
    created_at: nullableStr(row.created_at),
    updated_at: nullableStr(row.updated_at),
  };
}

/** Coerce an unknown row into a {@link ScimToken}, or `null` when malformed. */
function normalizeToken(value: unknown): ScimToken | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const id = str(row.id);
  if (!id) return null;
  return {
    id,
    workspace_id: str(row.workspace_id),
    prefix: str(row.prefix),
    token: nullableStr(row.token),
    revoked: row.revoked === true,
    last_used_at: nullableStr(row.last_used_at),
    created_at: nullableStr(row.created_at),
  };
}

// ---------------------------------------------------------------------------
// SSO connection (owner/admin — RBAC `workspace.settings`)
// ---------------------------------------------------------------------------

/**
 * GET /me/workspaces/{id}/sso — the workspace's CERT-FREE SSO connection, or
 * `null` when none is configured. Gated by `workspace.settings`: a non-member /
 * viewer gets a 403 (real workspace) or 404 (unknown id), surfaced as an
 * {@link ApiError}. The IdP cert / OIDC secret are never returned.
 */
export async function getSsoConnection(
  workspaceId: string,
  options?: RequestOptions,
): Promise<SsoConnection | null> {
  const data = await ssoRequest<unknown>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/sso`,
    { options },
  );
  return normalizeConnection(data);
}

/**
 * PUT /me/workspaces/{id}/sso — create/update the workspace's IdP connection.
 * Gated by `workspace.settings`. `idp_x509_cert` / `oidc_client_secret` are
 * write-only and Fernet-encrypted server-side; they are NEVER entered on mobile,
 * so this is used from the app only to flip `enabled` while re-sending the
 * connection's existing non-secret fields. Writes an `sso.configured` audit row
 * and returns the cert-free connection.
 */
export async function putSsoConnection(
  workspaceId: string,
  body: SsoConfigRequest,
  options?: RequestOptions,
): Promise<SsoConnection> {
  const data = await ssoRequest<unknown>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/sso`,
    { method: "PUT", body, options },
  );
  const connection = normalizeConnection(data);
  if (connection === null) {
    throw new ApiError(
      "Malformed response: expected an SSO connection from the API.",
      200,
      data,
    );
  }
  return connection;
}

/**
 * DELETE /me/workspaces/{id}/sso — remove the workspace's SSO connection. Gated by
 * `workspace.settings`; a 404 ({@link ApiError}) when none is configured. Writes
 * an `sso.deleted` audit row.
 */
export async function deleteSsoConnection(
  workspaceId: string,
  options?: RequestOptions,
): Promise<SsoDeleteResult> {
  const data = await ssoRequest<Partial<SsoDeleteResult>>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/sso`,
    { method: "DELETE", options },
  );
  return {
    deleted: data?.deleted === true,
    workspace_id: str(data?.workspace_id, workspaceId),
  };
}

// ---------------------------------------------------------------------------
// Security policy (owner/admin — RBAC `workspace.settings`)
// ---------------------------------------------------------------------------

/**
 * GET /me/workspaces/{id}/security — the workspace's security policy, or `null`
 * when none has been configured yet. Gated by `workspace.settings` (403 / 404 as
 * an {@link ApiError} otherwise). Never mutates anything.
 */
export async function getSecurityPolicy(
  workspaceId: string,
  options?: RequestOptions,
): Promise<SecurityPolicy | null> {
  const data = await ssoRequest<unknown>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/security`,
    { options },
  );
  return normalizePolicy(data);
}

/**
 * PUT /me/workspaces/{id}/security — apply a PARTIAL security-policy update (only
 * supplied fields change). Gated by `workspace.settings` (enforced before any
 * write) and audited server-side. Returns the persisted policy.
 */
export async function putSecurityPolicy(
  workspaceId: string,
  body: SecurityPolicyRequest,
  options?: RequestOptions,
): Promise<SecurityPolicy> {
  const data = await ssoRequest<unknown>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/security`,
    { method: "PUT", body, options },
  );
  const policy = normalizePolicy(data);
  if (policy === null) {
    throw new ApiError(
      "Malformed response: expected a security policy from the API.",
      200,
      data,
    );
  }
  return policy;
}

// ---------------------------------------------------------------------------
// SCIM tokens (owner/admin — RBAC `workspace.settings`)
// ---------------------------------------------------------------------------

/**
 * POST /me/workspaces/{id}/scim/tokens — mint a per-workspace SCIM bearer token.
 * The raw `token` is returned EXACTLY ONCE here (only its SHA-256 digest is
 * persisted); store/copy it now — it can never be retrieved again. Gated by
 * `workspace.settings`; writes a `scim.token_created` audit row.
 */
export async function createScimToken(
  workspaceId: string,
  options?: RequestOptions,
): Promise<ScimToken> {
  const data = await ssoRequest<unknown>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/scim/tokens`,
    { method: "POST", options },
  );
  const token = normalizeToken(data);
  if (token === null) {
    throw new ApiError(
      "Malformed response: expected a SCIM token from the API.",
      200,
      data,
    );
  }
  return token;
}

/**
 * GET /me/workspaces/{id}/scim/tokens — the workspace's SCIM tokens (ids,
 * prefixes, status). NEVER carries a raw token. Gated by `workspace.settings`.
 * The backend returns the list under `data`; a `{ tokens: [...] }` wrapper is
 * also tolerated. Malformed rows are dropped.
 */
export async function listScimTokens(
  workspaceId: string,
  options?: RequestOptions,
): Promise<ScimToken[]> {
  const data = await ssoRequest<ScimToken[] | { tokens?: ScimToken[] }>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/scim/tokens`,
    { options },
  );
  const rows = Array.isArray(data) ? data : (data?.tokens ?? []);
  return rows
    .map(normalizeToken)
    .filter((t): t is ScimToken => t !== null);
}

/**
 * DELETE /me/workspaces/{id}/scim/tokens/{tokenId} — revoke a workspace's SCIM
 * token. Workspace-scoped (a caller can never revoke another workspace's token);
 * a 404 ({@link ApiError}) when unknown. Gated by `workspace.settings`; writes a
 * `scim.token_revoked` audit row.
 */
export async function revokeScimToken(
  workspaceId: string,
  tokenId: string,
  options?: RequestOptions,
): Promise<ScimTokenRevokeResult> {
  const data = await ssoRequest<Partial<ScimTokenRevokeResult>>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/scim/tokens/${encodeURIComponent(
      tokenId,
    )}`,
    { method: "DELETE", options },
  );
  return {
    revoked: data?.revoked === true,
    token_id: str(data?.token_id, tokenId),
  };
}
