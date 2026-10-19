/**
 * Typed client + presentation helpers for the LLM SCRIPT generation engine —
 * the "write me a narration" surface behind `POST /api/v1/scripts`.
 *
 * The endpoint is stateless: it turns a subject (+ optional language, paragraph
 * count and style prompt) into a ready-to-narrate script string and returns it.
 * Nothing is persisted server-side, so the Script Studio keeps a device-local
 * library of generated scripts (see {@link module:src/shared/product/script-library})
 * and hands a chosen script to the reel-create flow.
 *
 * The wire transport (auth via `x-api-key`, JSON envelope unwrapping, typed
 * errors) is the shared api client; this module only adds the typed request
 * function and the side-effect-free domain helpers the screens layer on top.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

// ---------------------------------------------------------------------------
// Wire types (mirror app/models/schema.py VideoScriptParams / VideoScriptResponse)
// ---------------------------------------------------------------------------

/** Narration languages the studio offers (mirrors the reel `Language` union). */
export type ScriptLanguage = "auto" | "tr" | "en";

/** Body for `POST /api/v1/scripts`. Only `video_subject` is meaningful input. */
export interface GenerateScriptRequest {
  /** What the script should be about — the creator's brief. */
  readonly video_subject: string;
  /** Narration language. `""`/`"auto"` lets the model match the subject. */
  readonly video_language?: string;
  /** How many paragraphs to write (backend clamps to 1..10). */
  readonly paragraph_number?: number;
  /** Optional freeform style instruction ("punchy hook, casual tone", …). */
  readonly video_script_prompt?: string;
  /** Optional full system-prompt override (advanced / refine flows). */
  readonly custom_system_prompt?: string;
}

/** Result of `POST /api/v1/scripts` — the generated narration text. */
export interface GeneratedScript {
  readonly video_script: string;
}

// ---------------------------------------------------------------------------
// Backend limits (mirror the Pydantic Field constraints)
// ---------------------------------------------------------------------------

export const MIN_PARAGRAPHS = 1;
export const MAX_PARAGRAPHS = 10;
export const DEFAULT_PARAGRAPHS = 3;
/** Kept generous but bounded for a healthy subject line. */
export const MAX_SUBJECT_LEN = 500;
/** Matches `video_script_prompt` max_length in the schema. */
export const MAX_PROMPT_LEN = 2000;
/** Matches `custom_system_prompt` max_length in the schema. */
export const MAX_SYSTEM_PROMPT_LEN = 8000;

/** Selectable narration languages, in display order. */
export interface ScriptLanguageOption {
  readonly value: ScriptLanguage;
  readonly label: string;
}

export const SCRIPT_LANGUAGES: readonly ScriptLanguageOption[] = [
  { value: "auto", label: "Auto (match subject)" },
  { value: "en", label: "English" },
  { value: "tr", label: "Türkçe" },
];

// ---------------------------------------------------------------------------
// Wire call
// ---------------------------------------------------------------------------

/**
 * POST /api/v1/scripts — generate a narration script from a subject. The body
 * is normalized so only the fields the creator actually set ride the wire, and
 * the paragraph count is clamped to the backend's accepted range.
 */
export function generateScript(
  body: GenerateScriptRequest,
  options?: RequestOptions,
): Promise<GeneratedScript> {
  const subject = body.video_subject.trim();
  const prompt = (body.video_script_prompt ?? "").trim();
  const systemPrompt = (body.custom_system_prompt ?? "").trim();
  const language = (body.video_language ?? "").trim();

  const payload: GenerateScriptRequest = {
    video_subject: subject,
    paragraph_number: clampParagraphs(body.paragraph_number ?? DEFAULT_PARAGRAPHS),
    ...(language && language !== "auto" ? { video_language: language } : {}),
    ...(prompt ? { video_script_prompt: prompt } : {}),
    ...(systemPrompt ? { custom_system_prompt: systemPrompt } : {}),
  };

  return request<GeneratedScript>("/scripts", {
    method: "POST",
    body: payload,
    options,
  });
}

// ---------------------------------------------------------------------------
// Pure presentation / validation helpers (side-effect free)
// ---------------------------------------------------------------------------

/** Clamp a paragraph count into the backend's accepted 1..10 range. */
export function clampParagraphs(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_PARAGRAPHS;
  const rounded = Math.round(value);
  if (rounded < MIN_PARAGRAPHS) return MIN_PARAGRAPHS;
  if (rounded > MAX_PARAGRAPHS) return MAX_PARAGRAPHS;
  return rounded;
}

/**
 * Validate a subject line for the generate form. Returns a user-facing error
 * message, or `null` when the value is acceptable.
 */
export function validateSubject(subject: string): string | null {
  const trimmed = subject.trim();
  if (!trimmed) return "Enter what the script should be about.";
  if (trimmed.length < 3) return "Give a little more detail (3+ characters).";
  if (trimmed.length > MAX_SUBJECT_LEN) {
    return `Keep the subject under ${MAX_SUBJECT_LEN} characters.`;
  }
  return null;
}

/** Rough word count of a script (0 when empty). */
export function scriptWordCount(script: string): number {
  const trimmed = (script ?? "").trim();
  if (!trimmed) return 0;
  return trimmed.split(/\s+/).length;
}

/**
 * Estimated spoken length of a script in seconds, at a conversational
 * narration pace (~150 words per minute). Never negative.
 */
export function estimateNarrationSeconds(
  script: string,
  wordsPerMinute = 150,
): number {
  const words = scriptWordCount(script);
  if (words === 0 || wordsPerMinute <= 0) return 0;
  return Math.round((words / wordsPerMinute) * 60);
}

/** A compact "m:ss" duration label for a whole number of seconds. */
export function formatDuration(seconds: number): string {
  const safe = Math.max(0, Math.round(seconds));
  const mins = Math.floor(safe / 60);
  const secs = safe % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

/** A one-line "N words · ~m:ss" stat summary for a script. */
export function scriptStatsLine(script: string): string {
  const words = scriptWordCount(script);
  if (words === 0) return "Empty script";
  const duration = formatDuration(estimateNarrationSeconds(script));
  return `${words} ${words === 1 ? "word" : "words"} · ~${duration}`;
}

/** A human label for a language code, falling back to the raw value. */
export function languageLabel(code: string): string {
  const match = SCRIPT_LANGUAGES.find((l) => l.value === code);
  return match ? match.label : code || "Auto";
}
