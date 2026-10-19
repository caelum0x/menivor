/** Design Studio wire + canvas types (mirror apps/api/app/domains/design). */

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

export interface BrandColors {
  primary: string;
  accent: string;
  light: string;
  dark: string;
}

export interface BrandKitInfo {
  id: string;
  name: string;
  has_brand: boolean;
  logo_url: string | null;
  colors: BrandColors;
  fonts: { heading: string; body: string };
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
  copy: { headline: string; subline: string; cta: string; badge: string; points: string[] };
  copy_source: "llm" | "rules";
  brand: {
    brand_kit_id: string | null;
    name: string;
    colors: BrandColors;
    fonts: { heading: string; body: string };
    logo_key: string | null;
    has_brand: boolean;
  };
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
  used_ai_image: boolean;
  page_count: number;
  thumb_url: string | null;
  exported_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface DesignDoc extends DesignSummary {
  canvas: Canvas;
  exports: { key: string; url: string | null }[];
}

export interface StoredImage {
  key: string;
  asset_id: string;
  width: number;
  height: number;
  content_type: string;
  cost_micros?: number;
  model?: string | null;
}

export interface ApprovalItemView {
  id: string;
  source: string;
  title: string;
  status: string;
  payload: Record<string, unknown>;
}

export const SIZE_LABELS: Record<string, string> = {
  square: "Square post",
  portrait: "Portrait post",
  story: "Story / reel cover",
  landscape: "Link / feed landscape",
  carousel: "Carousel",
  banner: "Banner / header",
  app_store: "App store screenshot",
};

export const PLATFORM_OPTIONS: { id: string; label: string }[] = [
  { id: "instagram", label: "Instagram" },
  { id: "facebook", label: "Facebook" },
  { id: "linkedin", label: "LinkedIn" },
  { id: "x", label: "X" },
  { id: "threads", label: "Threads" },
  { id: "pinterest", label: "Pinterest" },
  { id: "bluesky", label: "Bluesky" },
  { id: "telegram", label: "Telegram" },
  { id: "discord", label: "Discord" },
  { id: "mastodon", label: "Mastodon" },
  { id: "app_store", label: "App Store listing" },
  { id: "play_store", label: "Google Play listing" },
  { id: "website", label: "Website" },
];
