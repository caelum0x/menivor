/**
 * Typed client for the character/brand "canon" governance engine — Expo.
 *
 * A canon locks a canonical identity (style, palette, typography, voice, product
 * and brand values, optionally bound to a saved character) into immutable,
 * content-hashed VERSIONS. Locking new values never mutates an old version — it
 * appends a new one and advances the header's `current_version`. A generation
 * (asset) can later be VERIFIED against a canon to prove it was produced under a
 * locked snapshot's values.
 *
 *   POST /canon                          create a canon + lock version 1
 *   POST /canon/{id}/lock                edit values => a new immutable version
 *   GET  /canon                          list the caller's canons (headers only)
 *   GET  /canon/{id}                      header + current version + version list
 *   GET  /canon/{id}/versions/{version}   one immutable locked snapshot (values)
 *   POST /canon/{id}/verify               {asset_id} => provenance/integrity check
 *
 * Every call is owner-scoped server-side (404 for a foreign/unknown id) and flows
 * through the shared `x-api-key` transport. No secrets here.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

/**
 * The locked value surface of a canon version. Mirrors the backend
 * `CanonValues`; every list field defaults to `[]` and every scalar to `""` so
 * the UI can render defensively.
 */
export interface CanonValues {
  character_identity_key: string;
  style: string;
  palette: string[];
  typography: string[];
  voice_id: string;
  voice_tone: string;
  language: string;
  product_name: string;
  product_descriptors: string[];
  product_claims: string[];
  brand_tone: string[];
  brand_avoid: string[];
}

/** A lightweight reference to one locked version (as listed on a header). */
export interface CanonVersionRef {
  version: number;
  canon_hash: string;
  locked_at: string;
}

/** One row from `GET /canon` — a canon header without its version values. */
export interface CanonSummary {
  canon_id: string;
  name: string;
  current_canon_hash: string;
  current_version: number;
}

/** `GET /canon/{id}` — header plus the full list of locked version refs. */
export interface CanonHeader {
  canon_id: string;
  name: string;
  character_id: string;
  current_canon_hash: string;
  current_version: number;
  versions: CanonVersionRef[];
}

/** `GET /canon/{id}/versions/{version}` — one immutable locked snapshot. */
export interface CanonVersionSnapshot {
  version: number;
  canon_hash: string;
  values: CanonValues;
  character_identity_key: string;
  locked_at: string;
}

/** The result of `POST /canon` or `POST /canon/{id}/lock`. */
export interface CanonLockResult {
  canon_id: string;
  canon_hash: string;
  version: number;
}

/** The result of `POST /canon/{id}/verify`. */
export interface CanonVerifyResult {
  verified: boolean;
  reason: string;
}

/** Request body for `POST /canon` — header `name` + optional bound character + values. */
export interface CreateCanonBody {
  name: string;
  character_id?: string;
  style?: string;
  palette?: string[];
  typography?: string[];
  voice_id?: string;
  voice_tone?: string;
  language?: string;
  product_name?: string;
  product_descriptors?: string[];
  product_claims?: string[];
  brand_tone?: string[];
  brand_avoid?: string[];
}

/**
 * Request body for `POST /canon/{id}/lock` — the same value surface as create,
 * minus the header `name`. A lock inherits the header's bound character unless
 * `character_id` is supplied.
 */
export interface LockCanonBody {
  character_id?: string;
  style?: string;
  palette?: string[];
  typography?: string[];
  voice_id?: string;
  voice_tone?: string;
  language?: string;
  product_name?: string;
  product_descriptors?: string[];
  product_claims?: string[];
  brand_tone?: string[];
  brand_avoid?: string[];
}

/** Request body for `POST /canon/{id}/verify`. */
export interface VerifyCanonBody {
  asset_id: string;
}

/**
 * Defensively coerce an unknown value into a `CanonValues`, so a sparse or
 * partial backend payload degrades to safe empties rather than crashing the UI.
 */
function normalizeValues(input: Partial<CanonValues> | undefined): CanonValues {
  const list = (v: unknown): string[] =>
    Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  const str = (v: unknown): string => (typeof v === "string" ? v : "");
  return {
    character_identity_key: str(input?.character_identity_key),
    style: str(input?.style),
    palette: list(input?.palette),
    typography: list(input?.typography),
    voice_id: str(input?.voice_id),
    voice_tone: str(input?.voice_tone),
    language: str(input?.language),
    product_name: str(input?.product_name),
    product_descriptors: list(input?.product_descriptors),
    product_claims: list(input?.product_claims),
    brand_tone: list(input?.brand_tone),
    brand_avoid: list(input?.brand_avoid),
  };
}

/**
 * POST /canon — create a canon and lock version 1 from the given values. Returns
 * the new canon id, its version-1 content hash, and the version number (1).
 */
export function createCanon(
  body: CreateCanonBody,
  options?: RequestOptions,
): Promise<CanonLockResult> {
  return request<CanonLockResult>("/canon", { method: "POST", body, options });
}

/**
 * POST /canon/{id}/lock — lock a NEW immutable version from edited values. Prior
 * versions are retained; the header's `current_version` advances. 404 for a
 * foreign/unknown canon.
 */
export function lockCanonVersion(
  canonId: string,
  body: LockCanonBody,
  options?: RequestOptions,
): Promise<CanonLockResult> {
  return request<CanonLockResult>(
    `/canon/${encodeURIComponent(canonId)}/lock`,
    { method: "POST", body, options },
  );
}

/**
 * GET /canon — the caller's canons (headers only). The backend returns them under
 * `canons`; the list is normalized so a blank payload degrades to `[]`.
 */
export async function listCanons(options?: RequestOptions): Promise<CanonSummary[]> {
  const data = await request<{ canons?: CanonSummary[] }>("/canon", { options });
  return Array.isArray(data?.canons) ? data.canons : [];
}

/**
 * GET /canon/{id} — one canon the caller owns (404 otherwise): its header plus
 * the full list of locked version refs (defensively normalized to `[]`).
 */
export async function getCanon(
  canonId: string,
  options?: RequestOptions,
): Promise<CanonHeader> {
  const data = await request<CanonHeader>(
    `/canon/${encodeURIComponent(canonId)}`,
    { options },
  );
  return {
    canon_id: data.canon_id,
    name: data.name,
    character_id: data.character_id ?? "",
    current_canon_hash: data.current_canon_hash,
    current_version: data.current_version,
    versions: Array.isArray(data.versions) ? data.versions : [],
  };
}

/**
 * GET /canon/{id}/versions/{version} — one immutable locked snapshot with its
 * full values (404 for an unknown version). Values are normalized defensively.
 */
export async function getCanonVersion(
  canonId: string,
  version: number,
  options?: RequestOptions,
): Promise<CanonVersionSnapshot> {
  const data = await request<CanonVersionSnapshot>(
    `/canon/${encodeURIComponent(canonId)}/versions/${encodeURIComponent(String(version))}`,
    { options },
  );
  return {
    version: data.version,
    canon_hash: data.canon_hash,
    values: normalizeValues(data.values),
    character_identity_key: data.character_identity_key ?? "",
    locked_at: data.locked_at,
  };
}

/**
 * POST /canon/{id}/verify — verify that an asset was produced under this canon's
 * locked values. Returns `{ verified, reason }`; an unstamped or wrongly-stamped
 * asset fails the provenance gate rather than erroring.
 */
export function verifyCanonAsset(
  canonId: string,
  body: VerifyCanonBody,
  options?: RequestOptions,
): Promise<CanonVerifyResult> {
  return request<CanonVerifyResult>(
    `/canon/${encodeURIComponent(canonId)}/verify`,
    { method: "POST", body, options },
  );
}
