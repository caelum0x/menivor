/**
 * Ad Studio API client: product URL -> ad angles -> rendered ad variants.
 *
 * The React Native port of apps/web/src/features/ad-studio/api.ts, over the
 * same `/v1/ad-studio/*` routes (apps/api/app/controllers/v1/adstudio.py).
 * Every call goes through the shared authenticated transport. UGC avatar ads
 * are started by posting the server-built `job_request` to the regular reel
 * pipeline (`POST /jobs`, one reel credit each) and then linking the created
 * job back to the ad. Showcase and before/after ads render for free.
 *
 * The helpers below the endpoints are pure and unit-tested.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type AdFormat = "showcase" | "before_after" | "ugc_avatar";
export type AdAspect = "9:16" | "1:1" | "16:9";
export type AdLanguage = "tr" | "en";
export type VariantStatus = "queued" | "rendering" | "ready" | "submitted" | "done" | "failed";

/** Server limit: angles x formats x aspects per batch request. */
export const MAX_BATCH = 30;
/** Angles drafted per analysis (the API accepts 3..5). */
export const ANGLE_COUNT = 5;
/** Reel credits one UGC avatar ad uses when its reel starts. */
export const AVATAR_AD_CREDITS = 1;

export interface AdFormatOption {
  readonly id: AdFormat;
  readonly label: string;
  readonly detail: string;
  /** True when rendering this format spends reel credits. */
  readonly usesCredits: boolean;
}

export const AD_FORMATS: readonly AdFormatOption[] = [
  {
    id: "showcase",
    label: "Product showcase",
    detail: "Your product photos with camera motion and on-screen captions. Rendered free.",
    usesCredits: false,
  },
  {
    id: "before_after",
    label: "Before / after",
    detail: "A muted before beat with the pain point, then the product with benefits. Rendered free.",
    usesCredits: false,
  },
  {
    id: "ugc_avatar",
    label: "UGC avatar",
    detail: "An AI avatar reads the script over a product montage. Uses 1 reel credit per ad.",
    usesCredits: true,
  },
];

export const AD_ASPECTS: readonly { id: AdAspect; label: string }[] = [
  { id: "9:16", label: "9:16 vertical" },
  { id: "1:1", label: "1:1 square" },
  { id: "16:9", label: "16:9 landscape" },
];

export interface Product {
  url: string;
  source: string;
  title: string;
  brand: string;
  description: string;
  price: number | null;
  original_price: number | null;
  currency: string;
  images: string[];
  bullets: string[];
  rating: number | null;
  review_count: number | null;
  reviews: string[];
  language: string;
}

export interface AdAngle {
  id: string;
  kind: string;
  label: string;
  hook: string;
  pain: string;
  proof: string;
  offer: string;
  cta: string;
  benefits: string[];
  script: string;
  source: string;
}

export interface ManualProductInput {
  title: string;
  brand?: string;
  description?: string;
  price?: number | null;
  original_price?: number | null;
  currency?: string;
  images?: string[];
  bullets?: string[];
  reviews?: string[];
  rating?: number | null;
  review_count?: number | null;
  language?: string;
  /** Store label when saving an already-analyzed product (no re-fetch). */
  source?: string;
}

export interface AnalyzeInput {
  url?: string;
  product?: ManualProductInput;
  language?: AdLanguage;
  angle_count?: number;
  use_llm?: boolean;
}

export interface AnalyzeResult {
  product: Product;
  language: AdLanguage;
  angles: AdAngle[];
}

export interface ProjectSummary {
  id: string;
  title: string;
  source: string;
  source_url: string | null;
  language: AdLanguage;
  angle_count: number;
  variant_count: number;
  done_count: number;
  thumbnail_url: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProjectImage {
  key: string;
  origin_url: string;
  width: number;
  height: number;
  url: string | null;
}

export interface AdVariant {
  id: string;
  angle_id: string;
  angle_label: string;
  format: AdFormat;
  format_label: string;
  aspect: AdAspect;
  status: VariantStatus;
  error: string | null;
  script: string;
  duration_s: number;
  poster_url: string | null;
  video_url: string | null;
  download_url: string | null;
  filename: string;
  job_id: string | null;
  job_request: Record<string, unknown> | null;
  montage_url: string | null;
  created_at: string | null;
}

export interface ProjectDetail extends ProjectSummary {
  product: Product;
  angles: AdAngle[];
  images: ProjectImage[];
  variants: AdVariant[];
}

export interface ExportItem {
  variant_id: string;
  filename: string;
  download_url: string;
  format: AdFormat;
  aspect: AdAspect;
  angle_label: string;
  script: string;
  post_caption: string;
}

export interface ExportManifest {
  project_id: string;
  title: string;
  items: ExportItem[];
  pending: number;
}

export type EditableAngle = Pick<AdAngle, "kind" | "hook" | "pain" | "proof" | "offer" | "cta" | "source">;

export interface CreateProjectInput extends AnalyzeInput {
  title?: string;
  angles?: EditableAngle[];
  image_keys?: string[];
}

export interface VariantsInput {
  angle_ids: string[];
  formats: AdFormat[];
  aspects: AdAspect[];
  avatar_id?: string;
  voice_id?: string;
}

export interface ProjectList {
  projects: ProjectSummary[];
  total: number;
  has_more: boolean;
}

const base = "/ad-studio";
const project = (id: string) => `${base}/projects/${encodeURIComponent(id)}`;
const variant = (id: string, variantId: string) =>
  `${project(id)}/variants/${encodeURIComponent(variantId)}`;

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

export function analyzeProduct(body: AnalyzeInput, options?: RequestOptions): Promise<AnalyzeResult> {
  return apiRequest<AnalyzeResult>(`${base}/analyze`, { method: "POST", body, options });
}

export function createAdProject(body: CreateProjectInput, options?: RequestOptions): Promise<ProjectDetail> {
  return apiRequest<ProjectDetail>(`${base}/projects`, { method: "POST", body, options });
}

export function listAdProjects(options?: RequestOptions): Promise<ProjectList> {
  return apiRequest<ProjectList>(`${base}/projects?limit=48`, { options });
}

export function getAdProject(id: string, options?: RequestOptions): Promise<ProjectDetail> {
  return apiRequest<ProjectDetail>(project(id), { options });
}

export function updateAdProject(
  id: string,
  body: { title?: string; angles?: EditableAngle[] },
  options?: RequestOptions,
): Promise<ProjectSummary> {
  return apiRequest<ProjectSummary>(project(id), { method: "PATCH", body, options });
}

export function regenerateAngles(
  id: string,
  body: { use_llm: boolean; angle_count?: number },
  options?: RequestOptions,
): Promise<{ angles: AdAngle[] }> {
  return apiRequest<{ angles: AdAngle[] }>(`${project(id)}/angles/regenerate`, {
    method: "POST",
    body,
    options,
  });
}

export function deleteAdProject(id: string, options?: RequestOptions): Promise<{ deleted: boolean }> {
  return apiRequest<{ deleted: boolean }>(project(id), { method: "DELETE", options });
}

export function createVariants(
  id: string,
  body: VariantsInput,
  options?: RequestOptions,
): Promise<{ variant_ids: string[]; queued: number }> {
  return apiRequest<{ variant_ids: string[]; queued: number }>(`${project(id)}/variants`, {
    method: "POST",
    body,
    options,
  });
}

export function retryVariant(
  id: string,
  variantId: string,
  options?: RequestOptions,
): Promise<{ status: VariantStatus }> {
  return apiRequest<{ status: VariantStatus }>(`${variant(id, variantId)}/retry`, {
    method: "POST",
    options,
  });
}

export function deleteVariant(
  id: string,
  variantId: string,
  options?: RequestOptions,
): Promise<{ deleted: boolean }> {
  return apiRequest<{ deleted: boolean }>(variant(id, variantId), { method: "DELETE", options });
}

export function exportAdProject(id: string, options?: RequestOptions): Promise<ExportManifest> {
  return apiRequest<ExportManifest>(`${project(id)}/export`, { options });
}

const REEL_KEY_PREFIX = "menivor.adstudio.reel-key.v1:";

/**
 * Idempotency key per ad and attempt, persisted so a crash or a double tap
 * never double-charges a UGC avatar reel.
 */
export async function avatarReelKey(adId: string): Promise<string> {
  const storageKey = REEL_KEY_PREFIX + adId;
  try {
    const existing = await AsyncStorage.getItem(storageKey);
    if (existing) return existing;
    const fresh = `adstudio-${adId}-${Date.now().toString(36)}`;
    await AsyncStorage.setItem(storageKey, fresh);
    return fresh;
  } catch {
    return `adstudio-${adId}`;
  }
}

/** Drop the stored key so a retried ad gets a fresh attempt. */
export async function forgetAvatarReelKey(adId: string): Promise<void> {
  try {
    await AsyncStorage.removeItem(REEL_KEY_PREFIX + adId);
  } catch {
    // Storage unavailable: nothing to forget.
  }
}

/**
 * Start a UGC avatar ad: submit its server-built reel request to `POST /jobs`
 * (idempotent per ad + attempt), then link the created job to the ad.
 */
export async function startAvatarReel(
  id: string,
  ad: AdVariant,
  options?: RequestOptions,
): Promise<{ job_id: string }> {
  if (!ad.job_request) throw new Error("This ad is not ready for an avatar reel yet.");
  const idempotencyKey = await avatarReelKey(ad.id);
  const job = await apiRequest<{ job_id: string }>("/jobs", {
    method: "POST",
    body: ad.job_request,
    options: { ...options, idempotencyKey },
  });
  await apiRequest(`${variant(id, ad.id)}/job`, {
    method: "POST",
    body: { job_id: job.job_id },
    options,
  });
  return { job_id: job.job_id };
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

/** The analyzed product as structured input, so saving does not re-fetch the page. */
export function productToInput(product: Product): ManualProductInput {
  return {
    title: product.title,
    brand: product.brand,
    description: product.description,
    price: product.price,
    original_price: product.original_price,
    currency: product.currency,
    images: product.images.slice(0, 10),
    bullets: product.bullets.slice(0, 8),
    reviews: product.reviews.slice(0, 6),
    rating: product.rating,
    review_count: product.review_count,
    language: product.language,
    source: product.source,
  };
}

/** The editable copy of each angle, as the create/update endpoints take it. */
export function editableAngles(angles: readonly AdAngle[]): EditableAngle[] {
  return angles.map(({ kind, hook, pain, proof, offer, cta, source }) => ({
    kind,
    hook,
    pain,
    proof,
    offer,
    cta,
    source,
  }));
}

export interface ManualDraft {
  title: string;
  brand: string;
  price: string;
  originalPrice: string;
  currency: string;
  bullets: string;
  images: string;
  description: string;
}

export const EMPTY_MANUAL: ManualDraft = {
  title: "",
  brand: "",
  price: "",
  originalPrice: "",
  currency: "USD",
  bullets: "",
  images: "",
  description: "",
};

export const MANUAL_CURRENCIES: readonly string[] = ["USD", "EUR", "GBP", "TRY"];

function toNumber(value: string): number | null {
  const n = Number(value.replace(",", ".").trim());
  return value.trim() !== "" && Number.isFinite(n) && n > 0 ? n : null;
}

function lines(value: string, max: number): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, max);
}

/** Manual product details as the analyze input (image lines must be http(s)). */
export function manualToInput(draft: ManualDraft): ManualProductInput {
  return {
    title: draft.title.trim(),
    brand: draft.brand.trim(),
    description: draft.description.trim(),
    price: toNumber(draft.price),
    original_price: toNumber(draft.originalPrice),
    currency: draft.currency,
    bullets: lines(draft.bullets, 8),
    images: lines(draft.images, 10).filter((url) => /^https?:\/\//i.test(url)),
  };
}

/** Validate the analyze form; returns an error message or "" when valid. */
export function validateAnalyze(mode: "url" | "manual", url: string, draft: ManualDraft): string {
  if (mode === "url") {
    return /^https?:\/\/\S+\.\S+/i.test(url.trim())
      ? ""
      : "Paste a full product link starting with https://";
  }
  return draft.title.trim() ? "" : "Enter the product name.";
}

/** Add `value` when absent, remove it when present (returns a new list). */
export function toggleIn<T>(list: readonly T[], value: T): T[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export interface BatchEstimate {
  /** Ads the batch renders (angles x formats x aspects). */
  readonly total: number;
  /** Ads that render free (showcase, before/after). */
  readonly free: number;
  /** UGC avatar ads; each uses reel credits when its reel starts. */
  readonly avatarAds: number;
  /** Reel credits the batch uses once every avatar reel is started. */
  readonly credits: number;
  readonly overLimit: boolean;
}

/** What a batch renders and what it will cost in reel credits. */
export function estimateBatch(
  angleCount: number,
  formats: readonly AdFormat[],
  aspectCount: number,
): BatchEstimate {
  const perFormat = Math.max(0, angleCount) * Math.max(0, aspectCount);
  const avatarAds = formats.includes("ugc_avatar") ? perFormat : 0;
  const total = perFormat * formats.length;
  return {
    total,
    free: total - avatarAds,
    avatarAds,
    credits: avatarAds * AVATAR_AD_CREDITS,
    overLimit: total > MAX_BATCH,
  };
}

/** One-line batch summary for the render button area. */
export function describeBatch(estimate: BatchEstimate): string {
  const ads = (n: number) => `${n} ad${n === 1 ? "" : "s"}`;
  if (estimate.total === 0) return "Pick at least one angle, format and aspect ratio.";
  if (estimate.overLimit) return `${ads(estimate.total)} is over the ${MAX_BATCH}-ad limit per batch.`;
  if (estimate.credits === 0) return `${ads(estimate.total)}, rendered free.`;
  const credits = `${estimate.credits} reel credit${estimate.credits === 1 ? "" : "s"}`;
  return estimate.free > 0
    ? `${ads(estimate.total)}: ${estimate.free} free, ${estimate.avatarAds} avatar (${credits} when you start them).`
    : `${ads(estimate.total)}: ${estimate.avatarAds} avatar (${credits} when you start them).`;
}

export function isActive(status: VariantStatus): boolean {
  return status === "queued" || status === "rendering" || status === "submitted";
}

export const STATUS_LABELS: Record<VariantStatus, string> = {
  queued: "Queued",
  rendering: "Rendering",
  ready: "Montage ready",
  submitted: "Avatar reel rendering",
  done: "Ready",
  failed: "Failed",
};

export const SOURCE_LABELS: Record<string, string> = {
  trendyol: "Trendyol",
  amazon: "Amazon",
  shopify: "Shopify",
  manual: "Entered manually",
  generic: "Web page",
};

export function formatPrice(value: number | null, currency: string, language: string): string {
  if (!value) return "";
  const locale = language === "tr" || currency === "TRY" ? "tr-TR" : "en-US";
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency: currency || (locale === "tr-TR" ? "TRY" : "USD"),
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${value} ${currency}`.trim();
  }
}

/** Plain-text posting sheet: one block per finished ad (filename + caption). */
export function captionsSheet(manifest: ExportManifest): string {
  return manifest.items
    .map((item) => `${item.filename} (${item.angle_label}, ${item.aspect})\n${item.post_caption}`)
    .join("\n\n");
}
