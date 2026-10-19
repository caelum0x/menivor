/**
 * Reel format availability + `format_locked` error handling, shared by every
 * create flow.
 *
 * `GET /launch/status` reports `available_formats` / `locked_formats` (with a
 * reason). A create call for a format the deployment cannot produce is
 * rejected with `402` + `data.code = "format_locked"` BEFORE any credit is
 * debited, so it must never be shown as "not enough credits". Everything here
 * is pure and parses network data defensively.
 */

export const FORMAT_LOCKED_CODE = "format_locked";

/** Format ids the API reports (mirrors `app/core/launch/formats.py`). */
export type FormatId =
  | "captions_only_byov"
  | "faceless_free_voice"
  | "typed_script"
  | "generated_script"
  | "premium_voice"
  | "avatar_reel"
  | "ai_broll"
  | "dub_video_free_voice"
  | "dub_video_premium_voice";

/** Readable fallback names when the server omits a label. */
const FORMAT_LABELS: Record<string, string> = {
  captions_only_byov: "Captions over your own video",
  faceless_free_voice: "Faceless narrated reel",
  typed_script: "Your own typed script",
  generated_script: "AI-written script",
  premium_voice: "Premium voices",
  avatar_reel: "AI avatar reel",
  ai_broll: "AI video",
  dub_video_free_voice: "Dubbing with a free voice",
  dub_video_premium_voice: "Dubbing with premium voices",
};

export interface LockedFormat {
  readonly id: string;
  readonly label: string;
  readonly reason: string;
}

export interface FormatAvailability {
  readonly available: readonly string[];
  readonly locked: Readonly<Record<string, LockedFormat>>;
}

/** Lock details carried by a `402 format_locked` API error. */
export interface FormatLock {
  readonly format: string;
  readonly label: string;
  readonly reason: string;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function formatLabel(id: string): string {
  return FORMAT_LABELS[id] ?? id.replace(/_/g, " ");
}

/**
 * Normalize the `GET /launch/status` data into availability. Returns `null`
 * when the document carries no format lists (older API): callers then allow
 * every option and rely on the server check at submit.
 */
export function parseFormatAvailability(raw: unknown): FormatAvailability | null {
  const rec = asRecord(raw);
  if (!rec) return null;
  const availableRaw = rec.available_formats;
  const lockedRaw = rec.locked_formats;
  if (!Array.isArray(availableRaw) && !Array.isArray(lockedRaw)) return null;

  const available = (Array.isArray(availableRaw) ? availableRaw : [])
    .map((entry) => text(asRecord(entry)?.id))
    .filter(Boolean);
  const locked: Record<string, LockedFormat> = {};
  for (const entry of Array.isArray(lockedRaw) ? lockedRaw : []) {
    const item = asRecord(entry);
    const id = text(item?.id);
    if (!id) continue;
    locked[id] = {
      id,
      label: text(item?.label) || formatLabel(id),
      reason: text(item?.reason) || "it is not set up on this server",
    };
  }
  return { available, locked };
}

/** The lock for `id`, or `null` when it is available (or availability is unknown). */
export function lockFor(
  availability: FormatAvailability | null | undefined,
  id: FormatId,
): LockedFormat | null {
  return availability?.locked[id] ?? null;
}

/** First locked format among `required`, in order. */
export function firstLock(
  availability: FormatAvailability | null | undefined,
  required: readonly FormatId[],
): LockedFormat | null {
  for (const id of required) {
    const lock = lockFor(availability, id);
    if (lock) return lock;
  }
  return null;
}

export interface ReelFormatInput {
  readonly layout: string;
  /** A typed script is sent (`video_script`). */
  readonly hasTypedScript: boolean;
  /** The creator's own narration is uploaded (`voiceover_key`). */
  readonly hasVoiceover?: boolean;
  /** A screen recording / own video is uploaded (`screen_recording_key`). */
  readonly hasScreenRecording?: boolean;
  /** A TTS voice is requested (`voice_name` non-empty). */
  readonly hasVoice?: boolean;
  /** The voice is an `elevenlabs:` voice AND ElevenLabs is available here. */
  readonly premiumVoiceUsable?: boolean;
}

/**
 * The formats a reel job needs, mirroring the server's `params_lock` and
 * `_needs_script_llm`. A premium (ElevenLabs) voice is never listed: without
 * its key the server narrates with a free voice instead of refusing, so the
 * free voice is what must be available.
 */
export function requiredReelFormats(input: ReelFormatInput): FormatId[] {
  const captionsOnly = input.layout === "captions_only";
  const hasVoiceover = input.hasVoiceover === true;
  const hasRecording = input.hasScreenRecording === true;
  const hasVoice = input.hasVoice === true;
  const required: FormatId[] = [];
  if (!captionsOnly) required.push("avatar_reel");

  const faceless = !hasVoiceover && !hasRecording && hasVoice;
  if (!input.hasTypedScript && (!captionsOnly || faceless)) {
    required.push("generated_script");
  }

  const synthesizesSpeech = !hasVoiceover && (!captionsOnly || (!hasRecording && hasVoice));
  // An ElevenLabs voice with its key set needs no free TTS fallback.
  if (synthesizesSpeech && input.premiumVoiceUsable !== true) {
    required.push("faceless_free_voice");
  }
  return required;
}

function statusOf(err: unknown): number | null {
  const status = asRecord(err)?.status;
  return typeof status === "number" ? status : null;
}

/**
 * The `format_locked` details of an API error, or `null`. Duck-typed on
 * `status` + `detail` so it works with any ApiError instance.
 */
export function formatLockOf(err: unknown): FormatLock | null {
  if (statusOf(err) !== 402) return null;
  const envelope = asRecord(asRecord(err)?.detail);
  const data = asRecord(envelope?.data);
  if (text(data?.code) !== FORMAT_LOCKED_CODE) return null;
  const format = text(data?.format);
  return {
    format,
    label: format ? formatLabel(format) : "This format",
    reason: text(data?.reason),
  };
}

/** A real credit shortfall: a 402 that is NOT a locked format. */
export function isCreditShortfall(err: unknown): boolean {
  return statusOf(err) === 402 && formatLockOf(err) === null;
}

/** Honest copy for a locked format. Names the format and why. */
export function formatLockedMessage(lock: FormatLock | LockedFormat): string {
  const reason = lock.reason ? `: ${lock.reason}` : "";
  return `${lock.label} is not available on this server yet${reason}. Nothing was charged.`;
}

/** Short reason line for a disabled option. */
export function lockedOptionReason(lock: LockedFormat): string {
  return `Not available on this server yet: ${lock.reason}.`;
}
