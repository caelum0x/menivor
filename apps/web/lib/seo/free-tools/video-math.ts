/**
 * Pure calculators behind the free video tools: aspect ratio / resolution
 * for TikTok, Reels and Shorts, and bitrate <-> file size. All units are
 * explicit; no DOM, so the math is unit-tested.
 */

export interface PlatformSpec {
  readonly key: string;
  readonly name: string;
  readonly ratio: string;
  readonly width: number;
  readonly height: number;
  readonly note: string;
}

/** Recommended upload sizes (public platform help pages, 2026). */
export const PLATFORM_SPECS: readonly PlatformSpec[] = [
  { key: "tiktok", name: "TikTok", ratio: "9:16", width: 1080, height: 1920, note: "Full-screen vertical. Keep text out of the bottom fifth and the right edge." },
  { key: "reels", name: "Instagram Reels", ratio: "9:16", width: 1080, height: 1920, note: "Grid preview crops to 3:4, so keep the subject centred." },
  { key: "shorts", name: "YouTube Shorts", ratio: "9:16", width: 1080, height: 1920, note: "Vertical or square, up to 3 minutes." },
  { key: "ig-feed-portrait", name: "Instagram feed (portrait)", ratio: "4:5", width: 1080, height: 1350, note: "Tallest ratio the feed shows without cropping." },
  { key: "square", name: "Square post", ratio: "1:1", width: 1080, height: 1080, note: "Feeds on Instagram, Facebook and LinkedIn." },
  { key: "youtube", name: "YouTube (landscape)", ratio: "16:9", width: 1920, height: 1080, note: "Standard HD; 3840x2160 for 4K." },
];

function gcd(a: number, b: number): number {
  let x = Math.abs(Math.round(a));
  let y = Math.abs(Math.round(b));
  while (y) {
    [x, y] = [y, x % y];
  }
  return x || 1;
}

/** Reduce width x height to the simplest ratio, e.g. 1080x1920 -> "9:16". */
export function simplifyRatio(width: number, height: number): string {
  if (!(width > 0) || !(height > 0)) return "";
  const divisor = gcd(width, height);
  return `${Math.round(width) / divisor}:${Math.round(height) / divisor}`;
}

/** Parse "9:16", "9x16" or "1.91:1" into a positive [w, h] pair. */
export function parseRatio(value: string): readonly [number, number] | null {
  const match = /^\s*(\d+(?:\.\d+)?)\s*[:x/]\s*(\d+(?:\.\d+)?)\s*$/i.exec(value);
  if (!match) return null;
  const w = Number(match[1]);
  const h = Number(match[2]);
  return w > 0 && h > 0 ? [w, h] : null;
}

/** Round to the nearest even pixel (H.264/H.265 need even dimensions). */
export function toEven(value: number): number {
  return Math.max(2, Math.round(value / 2) * 2);
}

/** Given a ratio and one side, compute the other side (even pixels). */
export function solveDimension(
  ratio: readonly [number, number],
  known: { readonly width?: number; readonly height?: number },
): { width: number; height: number } | null {
  const [rw, rh] = ratio;
  if (known.width && known.width > 0) {
    return { width: toEven(known.width), height: toEven((known.width * rh) / rw) };
  }
  if (known.height && known.height > 0) {
    return { width: toEven((known.height * rw) / rh), height: toEven(known.height) };
  }
  return null;
}

export interface FitResult {
  /** Scaled source size inside the target frame. */
  readonly width: number;
  readonly height: number;
  /** Bars (pad) or cropped pixels on each axis, total. */
  readonly padX: number;
  readonly padY: number;
  readonly mode: "pad" | "crop";
}

/**
 * Fit a source frame into a target frame. "pad" letterboxes (whole frame
 * visible), "crop" fills the target and trims the overflow.
 */
export function fitFrame(
  source: { readonly width: number; readonly height: number },
  target: { readonly width: number; readonly height: number },
  mode: "pad" | "crop",
): FitResult {
  const scaleX = target.width / source.width;
  const scaleY = target.height / source.height;
  const scale = mode === "pad" ? Math.min(scaleX, scaleY) : Math.max(scaleX, scaleY);
  const width = toEven(source.width * scale);
  const height = toEven(source.height * scale);
  return {
    width,
    height,
    padX: Math.abs(target.width - width),
    padY: Math.abs(target.height - height),
    mode,
  };
}

/** File size in megabytes (10^6 bytes) for a total bitrate and duration. */
export function fileSizeMB(videoKbps: number, audioKbps: number, durationSec: number): number {
  const totalKbps = Math.max(0, videoKbps) + Math.max(0, audioKbps);
  return (totalKbps * 1000 * Math.max(0, durationSec)) / 8 / 1_000_000;
}

/**
 * Video bitrate (kbps) that hits a target file size, after reserving audio
 * and ~2% container overhead. Never negative.
 */
export function videoBitrateForSize(
  targetMB: number,
  durationSec: number,
  audioKbps: number,
  overhead = 0.02,
): number {
  if (!(durationSec > 0) || !(targetMB > 0)) return 0;
  const totalKbps = (targetMB * 1_000_000 * 8 * (1 - overhead)) / durationSec / 1000;
  return Math.max(0, Math.floor(totalKbps - Math.max(0, audioKbps)));
}

/** Parse "1:30", "01:02:03" or "90" into seconds. */
export function parseDuration(value: string): number | null {
  const parts = value.trim().split(":").map((part) => part.trim());
  if (parts.length === 0 || parts.length > 3 || parts.some((p) => !/^\d+(\.\d+)?$/.test(p))) {
    return null;
  }
  return parts.reduce((total, part) => total * 60 + Number(part), 0);
}

export interface BitratePreset {
  readonly label: string;
  readonly width: number;
  readonly height: number;
  readonly fps: number;
  /** Typical H.264 kbps range for upload-quality short video. */
  readonly minKbps: number;
  readonly maxKbps: number;
}

/** Common H.264 upload bitrates (YouTube's published recommendations, SDR). */
export const BITRATE_PRESETS: readonly BitratePreset[] = [
  { label: "1080x1920 vertical, 30 fps", width: 1080, height: 1920, fps: 30, minKbps: 8000, maxKbps: 12000 },
  { label: "1080x1920 vertical, 60 fps", width: 1080, height: 1920, fps: 60, minKbps: 12000, maxKbps: 15000 },
  { label: "720x1280 vertical, 30 fps", width: 720, height: 1280, fps: 30, minKbps: 5000, maxKbps: 7500 },
  { label: "1920x1080 landscape, 30 fps", width: 1920, height: 1080, fps: 30, minKbps: 8000, maxKbps: 12000 },
  { label: "3840x2160 (4K), 30 fps", width: 3840, height: 2160, fps: 30, minKbps: 35000, maxKbps: 45000 },
];

/** Bits per pixel per frame: a codec-agnostic quality sanity check. */
export function bitsPerPixel(kbps: number, width: number, height: number, fps: number): number {
  if (!(width > 0 && height > 0 && fps > 0)) return 0;
  return (kbps * 1000) / (width * height * fps);
}

export interface SpeakingPacePreset {
  readonly label: string;
  readonly wpm: number;
}

/** Common spoken-word pacing presets for script/voiceover timing. */
export const SPEAKING_PACE_PRESETS: readonly SpeakingPacePreset[] = [
  { label: "Slow, deliberate", wpm: 120 },
  { label: "Natural speaking pace", wpm: 150 },
  { label: "Fast, energetic", wpm: 170 },
];

/** Spoken word count for a duration in seconds at a given words-per-minute pace. */
export function wordsForDuration(durationSec: number, wpm: number): number {
  if (!(durationSec > 0) || !(wpm > 0)) return 0;
  return Math.round((durationSec / 60) * wpm);
}

/** Duration in seconds needed to speak a word count at a given words-per-minute pace. */
export function durationForWords(words: number, wpm: number): number {
  if (!(words > 0) || !(wpm > 0)) return 0;
  return Math.round((words / wpm) * 60);
}
