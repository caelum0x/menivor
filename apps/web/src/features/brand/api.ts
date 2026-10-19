/**
 * Brand kit import client — website URL or Rally share link -> the caller's
 * brand kit (the same saved "brand kit" preset the reel wizard applies).
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type BrandImportSource = "website" | "rally";

export interface BrandColor {
  hex: string;
  /** Where the colour was read from: meta, css-variable, stylesheet or rally. */
  origin: string;
}

export interface BrandFont {
  family: string;
  origin: string;
}

export interface ImportedBrand {
  name: string;
  tagline: string;
  description: string;
  website_url: string;
  logo_url: string;
  image_url: string;
  colors: BrandColor[];
  fonts: BrandFont[];
  voice: string;
  audience: string;
  offer: string;
  language: string;
}

export interface BrandKitPreset {
  id: string;
  name: string;
  config: Record<string, unknown>;
  workspace_id: string | null;
  shared: boolean;
  created_at: string | null;
}

export interface BrandImportInput {
  source: BrandImportSource;
  /** Website URL, or a Rally brand kit share link / token. */
  value: string;
  /** false = preview only, nothing is saved. */
  save?: boolean;
  /** Update this kit instead of the one previously imported from the same source. */
  preset_id?: string;
  name?: string;
}

export interface BrandImportResult {
  source: BrandImportSource;
  source_key: string;
  brand: ImportedBrand;
  preset: BrandKitPreset | null;
}

export function importBrandKit(body: BrandImportInput, options?: RequestOptions): Promise<BrandImportResult> {
  return apiRequest<BrandImportResult>("/me/brand-kits/import", { method: "POST", body, options });
}
