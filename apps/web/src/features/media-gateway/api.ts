/**
 * Unified media gateway — OpenRouter-style /images + /videos over one key + one
 * wallet balance. Typed fns over `apiRequest` (which unwraps the envelope `.data`).
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import type {
  CreateVideoBody,
  MediaGenerationDetail,
  MediaGenerationPage,
  MediaIdentityOption,
  MediaJobView,
  MediaProvenanceExport,
} from "@reelforge/api-contract";

export type Modality = "image" | "video" | "audio";

export interface MediaModel {
  id: string;
  modality: Modality;
  provider: string;
  price_micros: number;
  unit: string; // "image" | "second"
  max_seconds: number;
  description: string;
}

export interface ImageResult {
  id: string;
  model: string;
  modality: "image";
  status: "completed";
  url: string;
  cost_micros: number;
}

export type VideoJob = MediaJobView;

export interface Credits {
  available_micros: number;
  reserved_micros: number;
  total_gateway_spend_micros: number;
  currency: string;
}

export interface UsageRow {
  model: string;
  modality: Modality;
  jobs: number;
  spend_micros: number;
  seconds: number;
}

export type GenerationDetail = MediaGenerationDetail;
export type GenerationPage = MediaGenerationPage;
export type IdentityOption = MediaIdentityOption;
export type ProvenanceExport = MediaProvenanceExport;

export type SettlementProofOutcome = "captured" | "released" | "pending" | "unsigned" | "unknown";

/** Client-safe interpretation of settlement evidence. Status alone is not proof. */
export interface SettlementProofView {
  outcome: SettlementProofOutcome;
  outcomeLabel: string;
  chargeLabel: string;
  proofLabel: string;
  operation: string | null;
  receiptHash: string | null;
  signature: string | null;
  signed: boolean;
  verified: boolean;
}

export function listMediaModels(
  modality?: Modality,
  options?: RequestOptions,
): Promise<{ models: MediaModel[] }> {
  const path = modality
    ? `/media/models?modality=${encodeURIComponent(modality)}`
    : "/media/models";
  return apiRequest<{ models: MediaModel[] }>(path, { options });
}

export function createImage(
  body: { model: string; prompt: string },
  options?: RequestOptions,
): Promise<ImageResult> {
  return apiRequest<ImageResult>("/media/images", { method: "POST", body, options });
}

export function createVideo(
  body: CreateVideoBody & { prompt: string },
  options?: RequestOptions,
): Promise<VideoJob> {
  return apiRequest<VideoJob>("/media/videos", { method: "POST", body, options });
}

export function getVideo(jobId: string, options?: RequestOptions): Promise<VideoJob> {
  return apiRequest<VideoJob>(`/media/videos/${encodeURIComponent(jobId)}`, { options });
}

export function createAudio(
  body: { model: string; prompt: string; instrumental?: boolean },
  options?: RequestOptions,
): Promise<VideoJob> {
  return apiRequest<VideoJob>("/media/audio", { method: "POST", body, options });
}

export function getAudio(jobId: string, options?: RequestOptions): Promise<VideoJob> {
  return apiRequest<VideoJob>(`/media/audio/${encodeURIComponent(jobId)}`, { options });
}

export function getCredits(options?: RequestOptions): Promise<Credits> {
  return apiRequest<Credits>("/media/credits", { options });
}

export function getUsage(options?: RequestOptions): Promise<{ usage: UsageRow[] }> {
  return apiRequest<{ usage: UsageRow[] }>("/media/usage", { options });
}

export function getGeneration(
  jobId: string,
  options?: RequestOptions,
): Promise<GenerationDetail> {
  return apiRequest<GenerationDetail>(`/media/generation/${encodeURIComponent(jobId)}`, { options });
}

export function listIdentityOptions(
  options?: RequestOptions,
): Promise<{ identities: IdentityOption[] }> {
  return apiRequest<{ identities: IdentityOption[] }>("/media/identities", { options });
}

export function getGenerationProvenance(
  jobId: string,
  options?: RequestOptions,
): Promise<ProvenanceExport> {
  return apiRequest<ProvenanceExport>(
    `/media/generation/${encodeURIComponent(jobId)}/provenance`,
    { options },
  );
}

export function listGenerations(
  params: {
    limit?: number;
    offset?: number;
    status?: string;
    modality?: Modality;
    refreshPending?: boolean;
  } = {},
  options?: RequestOptions,
): Promise<GenerationPage> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  if (params.status) query.set("status", params.status);
  if (params.modality) query.set("modality", params.modality);
  if (params.refreshPending !== undefined) {
    query.set("refresh_pending", String(params.refreshPending));
  }
  const suffix = query.size ? `?${query.toString()}` : "";
  return apiRequest<GenerationPage>(`/media/generations${suffix}`, { options });
}

/** Integer-microdollar → "$0.084" style display (1 USD = 1_000_000 micros). */
export function formatUsdMicros(micros: number): string {
  const usd = (micros || 0) / 1_000_000;
  const digits = usd !== 0 && Math.abs(usd) < 0.1 ? 3 : 2;
  return `$${usd.toFixed(digits)}`;
}

/**
 * Present settlement without equating a failed/released status with a charge.
 * A receipt operation is the only evidence of capture/release. Desktop-local
 * work is always represented as zero-cost and unsigned.
 */
export function settlementProofView(generation: GenerationDetail): SettlementProofView {
  const settlementRail = (generation as GenerationDetail & { settlement_rail?: string }).settlement_rail;
  if (
    generation.execution.kind === "desktop_local" ||
    settlementRail === "local" ||
    settlementRail === "desktop_local"
  ) {
    return {
      outcome: "unsigned",
      outcomeLabel: "Unsigned local execution",
      chargeLabel: "$0.00 charged",
      proofLabel: "No settlement receipt (local)",
      operation: null,
      receiptHash: null,
      signature: null,
      signed: false,
      verified: false,
    };
  }

  const evidence = generation.settlement_evidence as (NonNullable<GenerationDetail["settlement_evidence"]> & {
    verified?: boolean;
    attestation?: { digest_sha256?: string; signature_hex?: string } | null;
  }) | null;
  const receipt = evidence?.receipt;
  if (receipt) {
    const operation = receipt.operation?.trim() || null;
    const normalized = operation?.toLowerCase() || "";
    const captured = normalized === "capture" || normalized.endsWith(".capture");
    const released =
      normalized === "release" ||
      normalized === "void" ||
      normalized.endsWith(".release") ||
      normalized.endsWith(".void");
    const receiptHash = receipt.receipt_hash?.trim() || evidence?.attestation?.digest_sha256?.trim() || null;
    const signature = receipt.signature?.trim() || evidence?.attestation?.signature_hex?.trim() || null;
    const signed = Boolean(receiptHash && signature);
    const verified = evidence?.verified === true;
    const amountMicros = Number.isFinite(receipt.amount_micros) ? receipt.amount_micros : 0;

    return {
      outcome: captured ? "captured" : released ? "released" : "unknown",
      outcomeLabel: captured
        ? "Captured from receipt"
        : released
          ? "Released from receipt"
          : "Unknown receipt operation",
      chargeLabel: captured
        ? `${formatUsdMicros(amountMicros)} charged`
        : released
          ? "$0.00 charged"
          : `Receipt amount ${formatUsdMicros(amountMicros)}`,
      proofLabel: verified && signed
        ? "Verified signed settlement receipt"
        : signed
          ? "Signed receipt · verification not reported"
          : "Unsigned receipt data",
      operation,
      receiptHash,
      signature,
      signed,
      verified,
    };
  }

  if (generation.settlement_status === "held") {
    return {
      outcome: "pending",
      outcomeLabel: "Pending settlement",
      chargeLabel: `$0.00 charged · ${formatUsdMicros(generation.held_cost_micros)} held`,
      proofLabel: "No settlement receipt yet",
      operation: null,
      receiptHash: null,
      signature: null,
      signed: false,
      verified: false,
    };
  }

  const zeroCharge = generation.status === "failed" || generation.settlement_status === "released";
  return {
    outcome: "unsigned",
    outcomeLabel: "Settlement unverified",
    chargeLabel: zeroCharge
      ? "$0.00 charged"
      : `Reported cost ${formatUsdMicros(generation.effective_cost_micros)}`,
    proofLabel: "No signed settlement receipt",
    operation: null,
    receiptHash: null,
    signature: null,
    signed: false,
    verified: false,
  };
}

/** Per-unit price label, e.g. "$0.084 / second" or "$0.030 / image". */
export function priceLabel(m: MediaModel): string {
  return `${formatUsdMicros(m.price_micros)} / ${m.unit}`;
}

/**
 * Estimated integer-micro cost for a generation, mirroring the server's charge:
 * image + audio are flat per-generation; video is per-second × duration clamped
 * to `[1, max_seconds]` (0 = uncapped). Used for the client-side affordability
 * pre-flight before submitting.
 */
export function estimateCostMicros(
  m: MediaModel | undefined,
  modality: Modality,
  durationS: number,
): number {
  if (!m) return 0;
  if (modality !== "video") return m.price_micros;
  const seconds = Math.max(1, m.max_seconds > 0 ? Math.min(durationS, m.max_seconds) : durationS);
  return m.price_micros * seconds;
}
