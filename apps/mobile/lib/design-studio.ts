/**
 * Design Studio client — Expo. The same backend as the web's `/studio/design`
 * (`apps/api/app/domains/design/router.py`):
 *
 *   GET    /design/templates          size presets + built-in and saved templates
 *   GET    /design/brand-kits         the caller's brand kits
 *   POST   /design/generate           prompt + size + brand kit -> layout options
 *   GET    /design/docs               the caller's designs
 *   POST   /design/docs               create a design from a layout or saved template
 *   GET    /design/docs/{id}          one design (canvas + exported PNGs)
 *   PATCH  /design/docs/{id}          save title / canvas
 *   DELETE /design/docs/{id}          delete
 *   POST   /design/docs/{id}/duplicate
 *   GET    /design/media?key=…        bytes of an owned image (x-api-key)
 *
 * PNG export (`POST /design/docs/{id}/export`) takes pixel-exact PNGs rendered
 * by the client. The mobile app renders a live preview with plain views but has
 * no on-device rasterizer, so it lists and opens the exported PNGs and hands
 * rendering off to the web editor (see `webEditorUrl`).
 */

import { API_BASE, apiRequest as request, type RequestOptions } from "@/src/shared/api";

export type LayerType = "text" | "image" | "rect" | "ellipse" | "line";

export interface TextProps {
  text: string;
  fontFamily: string;
  fontSize: number;
  fontWeight: 400 | 700;
  italic?: boolean;
  color: string;
  align: "left" | "center" | "right";
  lineHeight: number;
  letterSpacing?: number;
  uppercase?: boolean;
}

export interface ImageProps {
  key: string;
  fit: "cover" | "contain";
  radius: number;
}

export interface ShapeProps {
  fill: string;
  stroke: string;
  strokeWidth: number;
  radius?: number;
}

export interface LineProps {
  stroke: string;
  strokeWidth: number;
}

interface LayerBase {
  id: string;
  name: string;
  x: number;
  y: number;
  width: number;
  height: number;
  rotation: number;
  opacity: number;
  locked?: boolean;
  hidden?: boolean;
}

export type Layer =
  | (LayerBase & { type: "text"; props: TextProps })
  | (LayerBase & { type: "image"; props: ImageProps })
  | (LayerBase & { type: "rect"; props: ShapeProps })
  | (LayerBase & { type: "ellipse"; props: ShapeProps })
  | (LayerBase & { type: "line"; props: LineProps });

export type TextLayer = Extract<Layer, { type: "text" }>;

export interface Page {
  background: string;
  layers: Layer[];
}

export interface Canvas {
  version: 1;
  pages: Page[];
}

export interface SizePreset {
  id: string;
  width: number;
  height: number;
}

export interface TemplateInfo {
  id: string | null;
  slug: string;
  name: string;
  description: string;
  presets: string[];
  builtin: boolean;
}

export interface BrandKitInfo {
  id: string;
  name: string;
  has_brand: boolean;
  logo_url: string | null;
}

export interface GeneratedOption {
  template: string;
  name: string;
  description: string;
  canvas: Canvas;
}

export interface GenerateResult {
  size_preset: string;
  width: number;
  height: number;
  copy_source: "llm" | "rules";
  brand: { brand_kit_id: string | null; name: string; has_brand: boolean };
  options: GeneratedOption[];
}

export type DesignStatus = "draft" | "exported" | "scheduled";

export interface DesignSummary {
  id: string;
  title: string;
  size_preset: string;
  width: number;
  height: number;
  template_id: string | null;
  brand_kit_id: string | null;
  prompt: string;
  status: DesignStatus;
  page_count: number;
  thumb_url: string | null;
  exported_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface DesignExport {
  key: string;
  url: string | null;
}

export interface DesignDoc extends DesignSummary {
  canvas: Canvas;
  exports: DesignExport[];
}

export const SIZE_LABELS: Readonly<Record<string, string>> = Object.freeze({
  square: "Square post",
  portrait: "Portrait post",
  story: "Story / reel cover",
  landscape: "Landscape",
  carousel: "Carousel",
  banner: "Banner / header",
  app_store: "App store screenshot",
});

export const MIN_PROMPT_CHARS = 3;
export const MAX_PROMPT_CHARS = 2000;
export const MAX_TITLE_CHARS = 200;
export const MAX_TEXT_CHARS = 600;

export function listDesignTemplates(
  options?: RequestOptions,
): Promise<{ sizes: SizePreset[]; templates: TemplateInfo[] }> {
  return request("/design/templates", { options });
}

export function listBrandKits(options?: RequestOptions): Promise<{ kits: BrandKitInfo[] }> {
  return request("/design/brand-kits", { options });
}

export function generateDesigns(
  body: { prompt: string; size_preset: string; brand_kit_id?: string | null },
  options?: RequestOptions,
): Promise<GenerateResult> {
  return request<GenerateResult>("/design/generate", {
    method: "POST",
    body: { ...body, use_llm: true },
    options,
  });
}

export function listDesigns(
  options?: RequestOptions,
  limit = 30,
): Promise<{ designs: DesignSummary[]; total: number }> {
  return request(`/design/docs?limit=${Math.max(1, Math.min(100, Math.trunc(limit) || 30))}&offset=0`, {
    options,
  });
}

export interface CreateDesignBody {
  title?: string;
  size_preset: string;
  canvas?: Canvas | null;
  template?: string;
  template_id?: string | null;
  brand_kit_id?: string | null;
  prompt?: string;
}

export function createDesign(body: CreateDesignBody, options?: RequestOptions): Promise<DesignDoc> {
  return request<DesignDoc>("/design/docs", { method: "POST", body, options });
}

export function getDesign(id: string, options?: RequestOptions): Promise<DesignDoc> {
  return request<DesignDoc>(`/design/docs/${encodeURIComponent(id)}`, { options });
}

export function saveDesign(
  id: string,
  body: { title?: string; canvas?: Canvas },
  options?: RequestOptions,
): Promise<DesignDoc> {
  return request<DesignDoc>(`/design/docs/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body,
    options,
  });
}

export function deleteDesign(id: string, options?: RequestOptions): Promise<{ deleted: boolean }> {
  return request(`/design/docs/${encodeURIComponent(id)}`, { method: "DELETE", options });
}

export function duplicateDesign(id: string, options?: RequestOptions): Promise<DesignDoc> {
  return request<DesignDoc>(`/design/docs/${encodeURIComponent(id)}/duplicate`, {
    method: "POST",
    options,
  });
}

// --------------------------------------------------------------------------- //
// Pure helpers
// --------------------------------------------------------------------------- //

/** Authenticated image source for an owned canvas image (React Native `Image`). */
export function designMediaSource(
  key: string,
  token: string | undefined,
): { uri: string; headers?: Record<string, string> } {
  const uri = `${API_BASE}/design/media?key=${encodeURIComponent(key)}`;
  return token ? { uri, headers: { "x-api-key": token } } : { uri };
}

const WEB_ORIGIN = (process.env.EXPO_PUBLIC_WEB_ORIGIN || "https://menivor.com").replace(/\/+$/, "");

/** The web editor for this design, where PNG pages are rendered and exported. */
export function webEditorUrl(id: string, origin: string = WEB_ORIGIN): string {
  return `${origin.replace(/\/+$/, "")}/studio/design/${encodeURIComponent(id)}`;
}

/** Templates offered for a size (built-ins list their presets; saved ones their own). */
export function templatesForSize(
  templates: readonly TemplateInfo[],
  size: string,
): TemplateInfo[] {
  return templates.filter((t) => t.presets.length === 0 || t.presets.includes(size));
}

/** Validate the generate form; returns the trimmed prompt or a readable error. */
export function validatePrompt(prompt: string): { ok: true; prompt: string } | { ok: false; error: string } {
  const clean = prompt.split(/\s+/).filter(Boolean).join(" ");
  if (clean.length < MIN_PROMPT_CHARS) {
    return { ok: false, error: "Describe the design in a few words." };
  }
  if (clean.length > MAX_PROMPT_CHARS) {
    return { ok: false, error: `Keep the description under ${MAX_PROMPT_CHARS} characters.` };
  }
  return { ok: true, prompt: clean };
}

/**
 * Generated options to show: when a built-in template is picked, that one
 * first (the server returns up to four per size), otherwise all of them.
 */
export function orderOptions(
  options: readonly GeneratedOption[],
  templateSlug: string,
): GeneratedOption[] {
  if (!templateSlug) return [...options];
  const picked = options.filter((o) => o.template === templateSlug);
  return [...picked, ...options.filter((o) => o.template !== templateSlug)];
}

export interface TextLayerRef {
  pageIndex: number;
  layer: TextLayer;
}

/** Every visible text layer, page by page (what the mobile editor lets you change). */
export function textLayers(canvas: Canvas): TextLayerRef[] {
  const refs: TextLayerRef[] = [];
  canvas.pages.forEach((page, pageIndex) => {
    page.layers.forEach((layer) => {
      if (layer.type === "text" && !layer.hidden) refs.push({ pageIndex, layer });
    });
  });
  return refs;
}

/** A new canvas with one text layer's text replaced; the input is not mutated. */
export function withLayerText(
  canvas: Canvas,
  pageIndex: number,
  layerId: string,
  text: string,
): Canvas {
  const clipped = text.slice(0, MAX_TEXT_CHARS);
  return {
    ...canvas,
    pages: canvas.pages.map((page, index) =>
      index !== pageIndex
        ? page
        : {
            ...page,
            layers: page.layers.map((layer) =>
              layer.id === layerId && layer.type === "text"
                ? { ...layer, props: { ...layer.props, text: clipped } }
                : layer,
            ),
          },
    ),
  };
}

/** True when the edited canvas differs from the saved one. */
export function canvasChanged(saved: Canvas, edited: Canvas): boolean {
  return JSON.stringify(saved) !== JSON.stringify(edited);
}

/** Exports that can be opened (the server could sign a URL for them). */
export function openableExports(doc: Pick<DesignDoc, "exports">): { page: number; url: string }[] {
  return doc.exports
    .map((e, i) => ({ page: i + 1, url: (e.url || "").trim() }))
    .filter((e) => e.url.length > 0);
}

/**
 * Whether the PNG exports still match the canvas. Any save after the last
 * export means the PNGs are stale and should be re-rendered.
 */
export function exportIsCurrent(doc: Pick<DesignDoc, "exported_at" | "updated_at" | "exports">): boolean {
  if (!doc.exported_at || doc.exports.length === 0) return false;
  if (!doc.updated_at) return true;
  const exported = Date.parse(doc.exported_at);
  const updated = Date.parse(doc.updated_at);
  if (Number.isNaN(exported) || Number.isNaN(updated)) return true;
  return exported >= updated - 1000;
}

/** Scale factor that fits a `width`x`height` design into `maxWidth` points. */
export function previewScale(width: number, height: number, maxWidth: number, maxHeight = Infinity): number {
  if (width <= 0 || height <= 0 || maxWidth <= 0) return 0;
  return Math.min(maxWidth / width, maxHeight / height);
}
