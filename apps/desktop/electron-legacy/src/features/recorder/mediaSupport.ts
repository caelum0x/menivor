/**
 * Runtime capability detection + MIME negotiation for `MediaRecorder`.
 *
 * Electron ships Chromium, which reliably records WebM (VP8/VP9); MP4/H.264
 * recording is available in some builds and is offered first when supported so
 * uploads land in the most broadly playable container, with WebM as the safe
 * fallback.
 */

/** A negotiated recording container: the `MediaRecorder` MIME + a file suffix. */
export interface MimeChoice {
  readonly mimeType: string;
  readonly extension: string;
}

/**
 * Preference order used when the caller does not supply its own. WebM is listed
 * ahead of MP4 because Chromium's `MediaRecorder` supports it everywhere; MP4
 * entries are kept as opportunistic upgrades where the build allows them.
 */
const DEFAULT_CANDIDATES: readonly MimeChoice[] = [
  { mimeType: "video/webm;codecs=vp9,opus", extension: "webm" },
  { mimeType: "video/webm;codecs=vp8,opus", extension: "webm" },
  { mimeType: "video/webm;codecs=vp9", extension: "webm" },
  { mimeType: "video/webm;codecs=vp8", extension: "webm" },
  { mimeType: "video/webm", extension: "webm" },
  { mimeType: "video/mp4;codecs=h264", extension: "mp4" },
  { mimeType: "video/mp4", extension: "mp4" },
];

/** Absolute last-resort container assumed to exist in any Chromium build. */
const FALLBACK: MimeChoice = { mimeType: "video/webm", extension: "webm" };

/**
 * True when the current runtime exposes the getDisplayMedia + MediaRecorder APIs
 * this module relies on. The panel uses this to render a friendly unsupported
 * state instead of throwing.
 */
export function isRecordingSupported(): boolean {
  return (
    typeof navigator !== "undefined" &&
    typeof navigator.mediaDevices !== "undefined" &&
    typeof navigator.mediaDevices.getDisplayMedia === "function" &&
    typeof MediaRecorder !== "undefined"
  );
}

/** Pick the first candidate the runtime can actually record, else the fallback. */
export function pickSupportedMimeType(
  preferred?: readonly MimeChoice[],
): MimeChoice {
  if (typeof MediaRecorder === "undefined") return FALLBACK;

  const candidates =
    preferred && preferred.length > 0 ? preferred : DEFAULT_CANDIDATES;

  for (const choice of candidates) {
    if (MediaRecorder.isTypeSupported(choice.mimeType)) return choice;
  }
  return FALLBACK;
}
