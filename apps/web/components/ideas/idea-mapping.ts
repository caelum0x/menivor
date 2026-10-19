/**
 * Pure helpers that project a SPARK {@link Idea} onto the create-job wizard and
 * resolve display labels for an idea's suggestion chips. Nothing here mutates
 * its inputs; every function returns a fresh value.
 */

import type { Idea } from "@/lib/types";
import type { SparkPrefill } from "@/lib/spark-prefill";
import {
  CAPTION_STYLE_OPTIONS,
  LANGUAGE_OPTIONS,
  LAYOUT_OPTIONS,
  coerceLanguage,
} from "@/components/wizard/types";

/**
 * Maps an idea to the wizard's prefill fields. `video_subject` is seeded from
 * the hook (plus angle for context); the optional script is seeded from the
 * numbered outline beats.
 */
export function ideaToPrefill(idea: Readonly<Idea>): SparkPrefill {
  const hook = idea.hook.trim();
  const angle = idea.angle.trim();
  const subject = hook
    ? angle && angle !== hook
      ? `${hook} — ${angle}`
      : hook
    : angle || idea.title.trim();

  const prompt = idea.script_outline
    .map((beat, i) => `${i + 1}. ${beat.trim()}`)
    .join("\n");

  return {
    videoSubject: subject,
    prompt,
    layout: idea.suggested_layout,
    captionStyle: idea.suggested_caption_style,
    // Idea languages are tr|en; coerce guards against anything unexpected.
    language: coerceLanguage(idea.language, "auto"),
  };
}

/** Human-readable name for a layout id, falling back to the raw id. */
export function layoutLabel(id: string): string {
  return LAYOUT_OPTIONS.find((o) => o.value === id)?.title ?? id;
}

/** Human-readable name for a language code, falling back to the raw code. */
export function languageLabel(code: string): string {
  return LANGUAGE_OPTIONS.find((o) => o.value === code)?.label ?? code;
}

export interface CaptionStyleMeta {
  label: string;
  /** Spoken-word swatch color. */
  spoken: string;
  /** Upcoming-word swatch color. */
  upcoming: string;
}

/** Display metadata (name + swatch colors) for a caption-style id. */
export function captionStyleMeta(id: string): CaptionStyleMeta {
  const match = CAPTION_STYLE_OPTIONS.find((o) => o.value === id);
  return {
    label: match?.title ?? id,
    spoken: match?.spoken ?? "#ffffff",
    upcoming: match?.upcoming ?? "#ffd60a",
  };
}
