/**
 * Unified media gateway contract — OpenRouter-style `/images` + `/videos` +
 * `/audio`. Stable client-facing shapes shared by the TypeScript/Python SDKs and
 * every first-party surface, plus the canonical endpoint paths. The OpenAPI
 * artifact (`openapi/reelforge-v1.json`) is the machine source of truth; this
 * module is the hand-curated, ergonomic mirror clients import.
 */

export type MediaModality = "image" | "video" | "audio";

/** A routable model in the unified catalog (`GET /media/models`). */
export interface MediaModel {
  id: string;
  modality: MediaModality;
  provider: string;
  price_micros: number;
  unit: string; // "image" | "second" | "clip"
  max_seconds: number;
  description: string;
}

/** Synchronous image result (`POST /images`). */
export interface MediaImageResult {
  id: string;
  model: string;
  modality: "image";
  status: "completed";
  url: string;
  cost_micros: number;
}

export interface MediaSettlementReceiptProof {
  sequence: number;
  operation: string;
  operation_hash: string;
  amount_micros: number;
  receipt_hash: string;
  signature: string;
}

/** Exact Mint envelope whose signature was verified against a pinned key. */
export interface MediaSettlementAttestation {
  format: "mint-hold-settlement-attestation-v1";
  payload_base64url: string;
  digest_sha256: string;
  signer_key_id: string;
  signature_hex: string;
}

/** Immutable Identity Lock + signed Mint binding for a generation. */
export interface MediaIdentityBinding {
  passport_id: string;
  version: number;
  content_digest: string;
  provider: string;
  status: "resolved" | "attestation_pending" | "attested" | "failed";
  provenance_id: string;
  request_id: string;
  payer_account: string;
  settled_at_ms: number;
  receipt: MediaSettlementReceiptProof | null;
}

/** Exact immutable passport head available to the authenticated Mint payer. */
export interface MediaIdentityOption {
  passport_id: string;
  kind: string;
  version: number;
  content_digest: string;
  status: "locked";
}

/** Portable verifier/export document for an identity-bound generation. */
export interface MediaProvenanceExport {
  schema: "menivor.media-provenance/v1";
  generation_id: string;
  modality: MediaModality;
  model: string;
  provider: string;
  status: string;
  output_url: string;
  correlation_id: string;
  identity: MediaIdentityBinding;
  settlement_evidence: MediaSettlementEvidence | null;
  margin_source: MediaMarginSource | null;
}

export interface MediaSettlementEvidence {
  rail: "mint";
  outcome: "captured" | "released";
  verified: true;
  request_id: string;
  principal: string;
  payer_account: string;
  receipt: MediaSettlementReceiptProof;
  attestation: MediaSettlementAttestation;
  settled_at_ms: number;
  verified_at_ms: number;
}

export interface MediaMarginSource {
  request_id: string;
  source: "reelforge";
  outcome: "succeeded";
  model: string;
  provider: string;
  cogs_micros: number;
  source_settlement_receipt: MediaSettlementReceiptProof & {
    request_id: string;
    payer_account: string;
  };
}

export interface MediaSettlementEvidenceExport extends MediaSettlementEvidence {
  schema: "railyard.settlement-evidence/v1";
  generation_id: string;
  provider_request_id: string;
  output_ref: string;
  provenance_id: string;
  margin_source: MediaMarginSource | null;
}

export interface MediaExecutionState {
  kind: "direct" | "prism" | "desktop_local";
  provider_request_id: string;
  resumable: boolean;
  /** Present only for durable desktop-local execution; cloud rows omit it. */
  local?: MediaLocalExecutionHistory | null;
}

/** Historical lease retained on an attempt after that lease stops being active. */
export interface MediaLocalAttemptLease {
  node_id: string;
  leased_at_s: number;
  expires_at_s: number;
}

/**
 * Verification result for one attempt's local output. `relative_reference` is
 * a portable forward-slash path confined to the desktop artifact root;
 * absolute and native host paths are never part of the shared contract.
 */
export interface MediaLocalArtifactVerification {
  verified: boolean;
  status:
    | "verified"
    | "missing"
    | "digest_mismatch"
    | "legacy_unverified"
    | "recovery_exhausted";
  content_id: string | null;
  sha256: string | null;
  observed_sha256: string | null;
  byte_length: number | null;
  relative_reference: string | null;
  execution_fingerprint: string;
  verified_at_s: number | null;
}

/** One immutable desktop-local execution attempt. Attempt numbers are 1-based. */
export interface MediaLocalAttempt {
  attempt: number;
  attempt_id: string;
  state: "queued" | "in_progress" | "completed" | "failed";
  outcome:
    | "queued"
    | "in_progress"
    | "verified"
    | "failed"
    | "artifact_missing"
    | "artifact_corrupt"
    | "recovery_exhausted"
    | "legacy_unverified";
  started_at_s: number;
  finished_at_s: number | null;
  lease: MediaLocalAttemptLease | null;
  artifact_verification: MediaLocalArtifactVerification | null;
  retry_parent_attempt: number | null;
  retry_reason: string | null;
}

/** Restart-durable, zero-cost local lineage nested under `execution.local`. */
export interface MediaLocalExecutionHistory {
  schema: "menivor.desktop-local-execution/v1";
  executor: string;
  execution_fingerprint: string;
  attempts: MediaLocalAttempt[];
}

/** Spendable credits + lifetime gateway spend (`GET /credits`). */
export interface MediaCredits {
  available_micros: number;
  reserved_micros: number;
  total_gateway_spend_micros: number;
  currency: string;
}

/** Spend + counts grouped by model (`GET /media/usage`). */
export interface MediaUsageRow {
  model: string;
  modality: MediaModality;
  jobs: number;
  spend_micros: number;
  seconds: number;
}

/** Canonical durable generation timeline row (`GET /media/generations`). */
export interface MediaGenerationDetail {
  id: string;
  model: string;
  modality: MediaModality;
  provider: string;
  status: "queued" | "in_progress" | "completed" | "failed";
  seconds: number;
  held_cost_micros: number;
  actual_cost_micros: number;
  effective_cost_micros: number;
  cost_micros: number;
  settlement_status: "held" | "settled" | "released";
  settlement_rail: "mint" | "local" | "desktop_local";
  output_url: string;
  url: string;
  error: string;
  correlation_id: string;
  provider_request_id: string;
  execution: MediaExecutionState;
  created_at: string | null;
  updated_at: string | null;
  is_terminal: boolean;
  identity?: MediaIdentityBinding | null;
  settlement_evidence: MediaSettlementEvidence | null;
  margin_source: MediaMarginSource | null;
}

/** Submit, poll, timeline, and detail all return this resumable superset. */
export type MediaJobView = MediaGenerationDetail;

export interface MediaGenerationPage {
  generations: MediaGenerationDetail[];
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface CreateImageBody {
  model: string;
  prompt: string;
}

export interface CreateVideoBody {
  model: string;
  prompt?: string;
  duration?: number;
  aspect_ratio?: string;
  image_url?: string;
  identity_passport_id?: string;
  identity_version?: number;
}

export interface CreateAudioBody {
  model: string;
  prompt: string;
  instrumental?: boolean;
}

/** Canonical media-gateway endpoint paths (relative to the `/api/v1` base).
 *  Namespaced under `/media` so they never collide with MPT's legacy routes. */
export const MEDIA_GATEWAY_PATHS = {
  models: "/media/models",
  images: "/media/images",
  videos: "/media/videos",
  video: (id: string) => `/media/videos/${encodeURIComponent(id)}`,
  audio: "/media/audio",
  audioJob: (id: string) => `/media/audio/${encodeURIComponent(id)}`,
  credits: "/media/credits",
  usage: "/media/usage",
  generations: "/media/generations",
  generation: (id: string) => `/media/generation/${encodeURIComponent(id)}`,
  identities: "/media/identities",
  provenance: (id: string) => `/media/generation/${encodeURIComponent(id)}/provenance`,
  evidence: (id: string) => `/media/generation/${encodeURIComponent(id)}/evidence`,
} as const;

/** Terminal statuses for a media job (video/audio). */
export const MEDIA_TERMINAL_STATUSES = ["completed", "failed"] as const;

export function isMediaJobTerminal(status: string): boolean {
  return (MEDIA_TERMINAL_STATUSES as readonly string[]).includes(status);
}
