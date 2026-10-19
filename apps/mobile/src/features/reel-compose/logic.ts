/**
 * Pure, framework-free helpers for the Reel Compose flow.
 *
 * Kept separate from the React components so the template→job translation and
 * input validation can be unit-tested without a renderer. No network, no state.
 */

import type { ReelDraft, TemplateInputDef } from "@/lib/templates";
import {
  LAYOUTS,
  isFailedState,
  isTerminalState,
  type JobCreateRequest,
  type Layout,
  type JobStateValue,
} from "@/lib/types";

/** Narrator-selector prefix understood by the backend's ElevenLabs TTS branch. */
export const ELEVENLABS_PREFIX = "elevenlabs:";

/** The full narrator selector for a catalog voice (`elevenlabs:<voice_id>`). */
export function catalogVoiceSelector(voiceId: string): string {
  return `${ELEVENLABS_PREFIX}${voiceId}`;
}

/** Narrow a free-form layout string to a known Layout, else use the fallback. */
export function coerceLayout(value: string, fallback: Layout = "pip"): Layout {
  return (LAYOUTS as readonly string[]).includes(value)
    ? (value as Layout)
    : fallback;
}

/** Stable idempotency key for a compose create (retained across retries). */
export function createIdempotencyKey(): string {
  return `compose-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export interface BuildJobInput {
  draft: ReelDraft;
  avatarId: string;
  voiceId: string;
  recordingKey: string;
  durationS: number;
  source?: { kind: "trend"; id: string; label?: string; forecastId?: string };
}

/**
 * Translate an instantiated template {@link ReelDraft} plus the creator's
 * avatar / voice / screen-recording selections into a valid POST /jobs body.
 *
 * The template supplies the creative direction (subject, script, layout,
 * caption + camera + music); the creator supplies the identity + footage the
 * pipeline needs. Empty optional fields are omitted so the request stays clean.
 */
export function buildJobRequest(input: BuildJobInput): JobCreateRequest {
  const { draft, avatarId, voiceId, recordingKey, durationS, source } = input;
  const selector = catalogVoiceSelector(voiceId);
  const script = (draft.video_script ?? "").trim();
  const musicPrompt = (draft.music_prompt ?? "").trim();
  const cameraMotion = (draft.camera_motion ?? "").trim();

  return {
    ...(source?.id
      ? {
          source_kind: source.kind,
          source_id: source.id,
          ...(source.label ? { source_label: source.label } : {}),
        }
      : {}),
    ...(source?.forecastId ? { forecast_id: source.forecastId } : {}),
    params: {
      video_subject: draft.video_subject.trim(),
      ...(script ? { video_script: script } : {}),
      voice_name: selector,
      avatar_id: avatarId,
      avatar_provider: "heygen",
      caption_style: draft.caption_style || "default",
      layout: coerceLayout(draft.layout),
      aspect: "9:16",
      language: "auto",
      target_duration_s: durationS,
      platforms: [],
      screen_recording_key: recordingKey,
    },
    avatar_id: avatarId,
    voice_id: voiceId,
    caption_style: draft.caption_style || "default",
    ...(musicPrompt ? { music_prompt: musicPrompt } : {}),
    ...(cameraMotion && cameraMotion !== "none"
      ? { camera_motion: cameraMotion as JobCreateRequest["camera_motion"] }
      : {}),
  };
}

/**
 * The keys of the required inputs a template still needs before it can be
 * instantiated, given the currently-entered values. Empty ⇒ ready to submit.
 */
export function missingRequiredInputs(
  inputs: readonly TemplateInputDef[],
  values: Readonly<Record<string, string>>,
): string[] {
  return inputs
    .filter((input) => input.required)
    .filter((input) => (values[input.key] ?? "").trim().length === 0)
    .map((input) => input.key);
}

/**
 * Seed the input-form value map from each input's default so the fields start
 * pre-filled with the template's suggested content (never mutates its args).
 */
export function defaultInputValues(
  inputs: readonly TemplateInputDef[],
): Record<string, string> {
  const seed: Record<string, string> = {};
  for (const input of inputs) {
    seed[input.key] =
      typeof input.default === "string" ? input.default : "";
  }
  return seed;
}

export type ReviewPhase = "queued" | "running" | "completed" | "failed";

/** Human-review phase for a polled job snapshot. */
export function reviewPhase(
  state: JobStateValue,
  progress: number,
): ReviewPhase {
  if (isFailedState(state)) return "failed";
  if (isTerminalState(state)) return "completed";
  return progress > 0 ? "running" : "queued";
}
