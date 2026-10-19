/**
 * A tiny, sessionStorage-backed handoff for SPARK → wizard prefill.
 *
 * The Ideas page stashes an idea's create-job-shaped fields here, then routes
 * to `/new`; the wizard reads (and clears) them once on mount to pre-fill its
 * form. sessionStorage keeps the payload off the URL and scoped to the tab.
 * Nothing here is a secret. All reads validate the untrusted stored value.
 */

import type { Language, Layout } from "@/lib/types";

/** The wizard-ready fields an idea contributes when "Make this" is clicked. */
export interface SparkPrefill {
  /** Seed for `params.video_subject` (derived from the idea's hook + angle). */
  videoSubject: string;
  /** Seed for the optional `params.video_script` (the idea's script outline). */
  prompt: string;
  /** Suggested composition layout. */
  layout: Layout;
  /** Suggested caption-style id. */
  captionStyle: string;
  /** Suggested output language. */
  language: Language;
}

const STORAGE_KEY = "reelforge:spark-prefill";

const LAYOUTS: readonly Layout[] = ["pip", "hook_intro", "split"];
const LANGUAGES: readonly Language[] = ["auto", "tr", "en"];

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** Narrows an untrusted parsed value back into a safe {@link SparkPrefill}. */
function coerce(value: unknown): SparkPrefill | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;

  const layout = LAYOUTS.includes(raw.layout as Layout)
    ? (raw.layout as Layout)
    : "pip";
  const language = LANGUAGES.includes(raw.language as Language)
    ? (raw.language as Language)
    : "auto";

  return {
    videoSubject: asString(raw.videoSubject),
    prompt: asString(raw.prompt),
    layout,
    captionStyle: asString(raw.captionStyle) || "karaoke_yellow",
    language,
  };
}

/** Persist a prefill for the wizard to pick up on its next mount. */
export function stashSparkPrefill(prefill: Readonly<SparkPrefill>): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(prefill));
  } catch {
    // sessionStorage may be unavailable (private mode/quota) — fail silently.
  }
}

/**
 * Read and remove the stashed prefill, if any. Returns `null` when nothing was
 * stashed or the stored value is unusable. Single-use by design.
 */
export function takeSparkPrefill(): SparkPrefill | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    window.sessionStorage.removeItem(STORAGE_KEY);
    return coerce(JSON.parse(raw) as unknown);
  } catch {
    return null;
  }
}
