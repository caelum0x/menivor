/**
 * Maps a SPARK {@link Idea} to the query params understood by the Create tab's
 * one-click prefill (`app/(tabs)/create.tsx`). This is the "Make this" bridge:
 * it turns a concept into a partial create-job form so the creator only has to
 * attach a screen recording and hit Create.
 *
 * Mapping (mirrors the web contract):
 * - `video_subject` <- hook + angle (the "what is this reel about" line)
 * - `video_script`  <- the script_outline beats, one per line
 * - `layout` / `caption_style` / `language` <- the idea's suggestions
 *
 * All values are strings because expo-router serialises route params to the
 * URL; empty fields are omitted so they never clobber a sensible default on the
 * Create screen.
 */

import type { Idea } from "@/lib/types";

/** Route-param key used to flag a prefill navigation on the Create screen. */
export const PREFILL_PARAM = "prefill";

/** The prefill params the Create screen reads via `useLocalSearchParams`. */
export interface CreatePrefillParams {
  /** Marks this navigation as a SPARK prefill (value is `"1"`). */
  prefill: string;
  /** `video_subject` — hook + angle. */
  subject?: string;
  /** `video_script` — script_outline beats joined by newlines. */
  script?: string;
  /** `params.layout` suggestion. */
  layout?: string;
  /** Top-level `caption_style` suggestion. */
  caption_style?: string;
  /** `params.language` suggestion. */
  language?: string;
  /** Router params are serialised to the URL; keep the shape index-compatible. */
  [key: string]: string | undefined;
}

/** Join the hook and angle into a single `video_subject` line. */
function subjectFromIdea(idea: Idea): string {
  const parts = [idea.hook, idea.angle]
    .map((p) => (typeof p === "string" ? p.trim() : ""))
    .filter(Boolean);
  return parts.join(" — ");
}

/** Join the script beats into a multi-line `video_script` block. */
function scriptFromIdea(idea: Idea): string {
  const beats = Array.isArray(idea.script_outline) ? idea.script_outline : [];
  return beats
    .map((b) => (typeof b === "string" ? b.trim() : ""))
    .filter(Boolean)
    .join("\n");
}

/**
 * Builds the (string-only) route params for navigating to the Create tab
 * prefilled from `idea`. Empty values are dropped so the Create screen keeps
 * its own defaults for anything the idea did not specify.
 */
export function ideaToCreateParams(idea: Idea): CreatePrefillParams {
  const params: CreatePrefillParams = { prefill: "1" };

  const subject = subjectFromIdea(idea) || (idea.title ?? "").trim();
  if (subject) params.subject = subject;

  const script = scriptFromIdea(idea);
  if (script) params.script = script;

  if (typeof idea.suggested_layout === "string" && idea.suggested_layout) {
    params.layout = idea.suggested_layout;
  }
  if (
    typeof idea.suggested_caption_style === "string" &&
    idea.suggested_caption_style
  ) {
    params.caption_style = idea.suggested_caption_style;
  }
  if (typeof idea.language === "string" && idea.language) {
    params.language = idea.language;
  }

  return params;
}
