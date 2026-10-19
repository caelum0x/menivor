import type { UserVoice } from "@/lib/types";

/**
 * Shared constants + helpers for the Brand Voice (voice cloning) surfaces.
 * Kept framework-free so both the manager page and the wizard voice picker can
 * import them without pulling in React.
 */

/** Narrator-selector prefix used by the backend (`voice_name` / `voice_id`). */
export const ELEVENLABS_PREFIX = "elevenlabs:";

/** Clone status the backend reports once a voice is usable. */
export const READY_STATUS = "ready";

/** Max accepted voice-sample size (bytes). Samples are short (30-60s). */
export const MAX_SAMPLE_BYTES = 25 * 1024 * 1024; // 25 MB

/** Recommended sample length window, surfaced as UI guidance. */
export const MIN_SAMPLE_SECONDS = 30;
export const MAX_SAMPLE_SECONDS = 60;

/**
 * Strip the `"elevenlabs:"` prefix from a cloned voice's `voice_id`, yielding
 * the bare provider voice id. The wizard stores the bare id and re-adds the
 * prefix when building the job (`voice_name = "elevenlabs:<id>"`), so a cloned
 * voice must be normalized the same way curated voices are to avoid a
 * double-prefixed `elevenlabs:elevenlabs:<id>`.
 */
export function stripElevenLabsPrefix(voiceId: string): string {
  return voiceId.startsWith(ELEVENLABS_PREFIX)
    ? voiceId.slice(ELEVENLABS_PREFIX.length)
    : voiceId;
}

/** Whether a cloned voice has finished cloning and is selectable. */
export function isVoiceReady(voice: UserVoice): boolean {
  return (voice.status || "").toLowerCase() === READY_STATUS;
}

/** Human-readable creation date, or `null` when unavailable/unparseable. */
export function formatCreatedAt(createdAt?: string | null): string | null {
  if (!createdAt) return null;
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
