/**
 * Ad Studio API client — product URL -> ad angles -> rendered ad variants.
 *
 * Every call goes through the shared authenticated transport. UGC avatar ads
 * are started by posting the server-built `job_request` to the regular reel
 * pipeline (`POST /jobs`) and then linking the created job back to the ad.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type AdFormat = "showcase" | "before_after" | "ugc_avatar";
export type AdAspect = "9:16" | "1:1" | "16:9";
export type AdLanguage = "tr" | "en";
export type VariantStatus = "queued" | "rendering" | "ready" | "submitted" | "done" | "failed";

export const AD_FORMATS: { id: AdFormat; label: string; detail: string }[] = [
  {
    id: "showcase",
    label: "Product showcase",
    detail: "Your product photos with camera motion and on-screen captions. Rendered free.",
  },
  {
    id: "before_after",
    label: "Before / after",
    detail: "A muted before beat with the pain point, then the product with benefits. Rendered free.",
  },
  {
    id: "ugc_avatar",
    label: "UGC avatar",
    detail: "An AI avatar reads the script over a product montage. Uses your normal reel credits.",
  },
];

export const AD_ASPECTS: { id: AdAspect; label: string }[] = [
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
  /** The opening line this ad was rendered with. */
  hook: string;
  /** Set while/after the ad is part of a "Publish and test" run. */
  test_batch_id: string | null;
  /** The winning ad this one was remade from, if any. */
  remake_of: string | null;
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

const base = "/ad-studio";
const project = (id: string) => `${base}/projects/${encodeURIComponent(id)}`;
const variant = (id: string, variantId: string) =>
  `${project(id)}/variants/${encodeURIComponent(variantId)}`;

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

export function analyzeProduct(body: AnalyzeInput, options?: RequestOptions): Promise<AnalyzeResult> {
  return apiRequest<AnalyzeResult>(`${base}/analyze`, { method: "POST", body, options });
}

export function createAdProject(body: CreateProjectInput, options?: RequestOptions): Promise<ProjectDetail> {
  return apiRequest<ProjectDetail>(`${base}/projects`, { method: "POST", body, options });
}

export interface ProjectList {
  projects: ProjectSummary[];
  total: number;
  has_more: boolean;
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
  return apiRequest(`${project(id)}/variants`, { method: "POST", body, options });
}

export function retryVariant(id: string, variantId: string, options?: RequestOptions): Promise<{ status: VariantStatus }> {
  return apiRequest(`${variant(id, variantId)}/retry`, { method: "POST", options });
}

export function deleteVariant(id: string, variantId: string, options?: RequestOptions): Promise<{ deleted: boolean }> {
  return apiRequest(variant(id, variantId), { method: "DELETE", options });
}

export function exportAdProject(id: string, options?: RequestOptions): Promise<ExportManifest> {
  return apiRequest<ExportManifest>(`${project(id)}/export`, { options });
}

/**
 * Start a UGC avatar ad: submit its server-built reel request to `POST /jobs`
 * (idempotent per ad + attempt), then link the created job to the ad.
 */
export async function startAvatarReel(
  id: string,
  ad: AdVariant,
  idempotencyKey: string,
  options?: RequestOptions,
): Promise<{ job_id: string }> {
  if (!ad.job_request) throw new Error("This ad is not ready for an avatar reel yet.");
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

export function isActive(status: VariantStatus): boolean {
  return status === "queued" || status === "rendering" || status === "submitted";
}

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
