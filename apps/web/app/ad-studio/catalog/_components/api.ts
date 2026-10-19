/**
 * Store catalog import client: read a Shopify or WooCommerce store's public
 * product feed and turn picked products into Ad Studio projects. Prices are in
 * the store currency's minor units; `null` means the feed had no price.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type StoreProvider = "shopify" | "woocommerce";
export type ProviderChoice = StoreProvider | "auto";
export type ImportStatus = "queued" | "running" | "succeeded" | "failed";

export const MAX_PRODUCTS_PER_IMPORT = 250;
export const MAX_PROJECTS_PER_CALL = 5;

export interface StoreImport {
  id: string;
  provider: StoreProvider;
  provider_requested: ProviderChoice;
  currency: string;
  store_url: string;
  store_name: string;
  status: ImportStatus;
  requested_limit: number;
  product_count: number;
  error: string | null;
  created_projects: number | null;
  created_at: string | null;
  finished_at: string | null;
}

export interface StoreProduct {
  id: string;
  external_id: string;
  title: string;
  description: string;
  price_minor: number | null;
  compare_at_minor: number | null;
  currency: string;
  url: string;
  image_urls: string[];
  tags: string[];
  adstudio_project_id: string | null;
}

export interface StoreImportDetail extends StoreImport {
  products: StoreProduct[];
}

export interface ProjectResult {
  product_id: string;
  project_id: string | null;
  error: string;
}

export function listImports(options?: RequestOptions): Promise<{ imports: StoreImport[]; total: number }> {
  return apiRequest<{ imports: StoreImport[]; total: number }>("/ad-studio/catalog/imports", { options });
}

export function createImport(
  body: { store_url: string; provider: ProviderChoice; limit: number },
  options?: RequestOptions,
): Promise<StoreImportDetail> {
  return apiRequest<StoreImportDetail>("/ad-studio/catalog/imports", { method: "POST", body, options });
}

export function getImport(id: string, options?: RequestOptions): Promise<StoreImportDetail> {
  return apiRequest<StoreImportDetail>(`/ad-studio/catalog/imports/${encodeURIComponent(id)}`, { options });
}

export function deleteImport(id: string, options?: RequestOptions): Promise<unknown> {
  return apiRequest<unknown>(`/ad-studio/catalog/imports/${encodeURIComponent(id)}`, { method: "DELETE", options });
}

export function createProjects(
  id: string,
  body: { product_ids: string[]; use_llm: boolean; language?: string },
  options?: RequestOptions,
): Promise<{ results: ProjectResult[]; created: number }> {
  return apiRequest<{ results: ProjectResult[]; created: number }>(
    `/ad-studio/catalog/imports/${encodeURIComponent(id)}/projects`,
    { method: "POST", body, options },
  );
}

export function providerLabel(provider: ProviderChoice): string {
  if (provider === "shopify") return "Shopify";
  if (provider === "woocommerce") return "WooCommerce";
  return "Auto-detect";
}
