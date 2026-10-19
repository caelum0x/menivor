/**
 * Shared shapes + pure helpers for saved presets ("Brand Kits").
 *
 * A preset's `config` is an opaque `Record<string, unknown>` on the wire (see
 * `Preset` in `@/lib/types`). This module gives that map a typed, validated
 * projection — the subset of ReelForge settings a brand kit captures — plus
 * pure helpers to coerce, serialise, and summarise it for display. Nothing here
 * mutates its inputs; every function returns a fresh value.
 */

import {
  CAPTION_STYLE_OPTIONS,
  LANGUAGE_OPTIONS,
  LAYOUT_OPTIONS,
} from "@/components/wizard/types";

/**
 * The typed projection of a preset's opaque config map. Keys mirror the fields
 * that both the create-job wizard and `RerunOverrides` understand, so a brand
 * kit can pre-fill a new reel or a re-run.
 */
export interface PresetConfig {
  avatar_id?: string;
  voice_id?: string;
  /** Human-readable voice name, stored alongside the id for nicer summaries. */
  voice_label?: string;
  layout?: string;
  caption_style?: string;
  music_id?: string;
  language?: string;
}

/** The known string keys of a {@link PresetConfig}. */
const CONFIG_KEYS: readonly (keyof PresetConfig)[] = [
  "avatar_id",
  "voice_id",
  "voice_label",
  "layout",
  "caption_style",
  "music_id",
  "language",
];

/** Reads a value as a trimmed non-empty string, or `undefined`. */
function asString(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

/**
 * Safely narrows an opaque config map (untrusted API data) to a
 * {@link PresetConfig}, keeping only recognised string fields.
 */
export function coercePresetConfig(
  config: Readonly<Record<string, unknown>> | null | undefined,
): PresetConfig {
  if (!config || typeof config !== "object") return {};
  const out: PresetConfig = {};
  for (const key of CONFIG_KEYS) {
    const value = asString(config[key]);
    if (value !== undefined) out[key] = value;
  }
  return out;
}

/**
 * Serialises a {@link PresetConfig} to the wire `config` record, dropping empty
 * fields so the backend only stores what the user actually set.
 */
export function toConfigRecord(
  config: Readonly<PresetConfig>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of CONFIG_KEYS) {
    const value = asString(config[key]);
    if (value !== undefined) out[key] = value;
  }
  return out;
}

/** Returns true when the config carries at least one meaningful field. */
export function isConfigEmpty(config: Readonly<PresetConfig>): boolean {
  return Object.keys(toConfigRecord(config)).length === 0;
}

// ---------------------------------------------------------------------------
// Display summary
// ---------------------------------------------------------------------------

/**
 * Optional id → display-name maps (built from the live catalogs) used to render
 * friendly labels in a preset summary. When a map is absent the raw id is shown.
 */
export interface PresetLabelMaps {
  caption?: Readonly<Record<string, string>>;
  music?: Readonly<Record<string, string>>;
  layout?: Readonly<Record<string, string>>;
  language?: Readonly<Record<string, string>>;
}

export interface PresetSummaryItem {
  key: keyof PresetConfig;
  label: string;
  value: string;
}

/** Static fallbacks derived from the wizard's built-in option lists. */
const STATIC_LAYOUT: Record<string, string> = Object.fromEntries(
  LAYOUT_OPTIONS.map((o) => [o.value, o.title]),
);
const STATIC_CAPTION: Record<string, string> = Object.fromEntries(
  CAPTION_STYLE_OPTIONS.map((o) => [o.value, o.title]),
);
const STATIC_LANGUAGE: Record<string, string> = Object.fromEntries(
  LANGUAGE_OPTIONS.map((o) => [o.value, o.label]),
);

function resolve(
  value: string,
  live: Readonly<Record<string, string>> | undefined,
  fallback: Readonly<Record<string, string>>,
): string {
  return live?.[value] ?? fallback[value] ?? value;
}

/**
 * Projects a config into an ordered list of `{ label, value }` rows for display.
 * Only fields that carry a value are included, so an empty kit yields `[]`.
 */
export function summarizePresetConfig(
  config: Readonly<PresetConfig>,
  maps: Readonly<PresetLabelMaps> = {},
): PresetSummaryItem[] {
  const items: PresetSummaryItem[] = [];

  if (config.avatar_id) {
    items.push({ key: "avatar_id", label: "Avatar", value: config.avatar_id });
  }
  const voice = config.voice_label ?? config.voice_id;
  if (voice) {
    items.push({ key: "voice_id", label: "Voice", value: voice });
  }
  if (config.layout) {
    items.push({
      key: "layout",
      label: "Layout",
      value: resolve(config.layout, maps.layout, STATIC_LAYOUT),
    });
  }
  if (config.caption_style) {
    items.push({
      key: "caption_style",
      label: "Captions",
      value: resolve(config.caption_style, maps.caption, STATIC_CAPTION),
    });
  }
  if (config.music_id) {
    items.push({
      key: "music_id",
      label: "Music",
      value: resolve(config.music_id, maps.music, {}),
    });
  }
  if (config.language) {
    items.push({
      key: "language",
      label: "Language",
      value: resolve(config.language, maps.language, STATIC_LANGUAGE),
    });
  }

  return items;
}
