/** Client-side timeline (EDL) model — mirrors the server timeline policy. */

export type OverlayPosition = "top" | "center" | "bottom";

export interface TimelineSegment {
  id: string;
  sourceIn: number;
  sourceOut: number;
  speed: number;
  caption: string;
}

export interface TextOverlay {
  id: string;
  text: string;
  startS: number;
  endS: number;
  position: OverlayPosition;
}

export const MIN_SEGMENT_S = 0.1;
export const MIN_SPEED = 0.25;
export const MAX_SPEED = 4;
export const MAX_SEGMENTS = 200;
export const MAX_OVERLAYS = 50;
export const MAX_TEXT_LENGTH = 200;

let _counter = 0;
function nextId(prefix: string): string {
  _counter += 1;
  return `${prefix}-${_counter}`;
}

export function newSegment(sourceIn: number, sourceOut: number): TimelineSegment {
  return { id: nextId("seg"), sourceIn, sourceOut, speed: 1, caption: "" };
}

export function newOverlay(endS: number): TextOverlay {
  return { id: nextId("ov"), text: "", startS: 0, endS: Math.max(0.1, endS), position: "bottom" };
}

/** Output length of one segment (source range scaled by speed). */
export function segmentOutputLen(seg: TimelineSegment): number {
  const speed = Math.min(MAX_SPEED, Math.max(MIN_SPEED, seg.speed || 1));
  return Math.max(0, (seg.sourceOut - seg.sourceIn) / speed);
}

/** Total output duration of the timeline (sum of scaled segment lengths). */
export function timelineDuration(segments: readonly TimelineSegment[]): number {
  return Number(segments.reduce((acc, s) => acc + segmentOutputLen(s), 0).toFixed(3));
}

/** Return a human-readable validation error, or null when the EDL is valid. */
export function validateTimeline(
  segments: readonly TimelineSegment[],
  overlays: readonly TextOverlay[],
  sourceDuration: number,
): string | null {
  if (!Number.isFinite(sourceDuration) || sourceDuration <= 0) {
    return "Wait for the source video metadata.";
  }
  if (segments.length === 0) return "Add at least one segment.";
  if (segments.length > MAX_SEGMENTS) return `Use at most ${MAX_SEGMENTS} segments.`;
  if (overlays.length > MAX_OVERLAYS) return `Use at most ${MAX_OVERLAYS} overlays.`;
  for (const [i, s] of segments.entries()) {
    if (![s.sourceIn, s.sourceOut, s.speed].every(Number.isFinite)) {
      return `Segment ${i + 1}: values must be finite numbers.`;
    }
    if (s.sourceIn < 0) return `Segment ${i + 1}: start cannot be negative.`;
    if (s.sourceOut <= s.sourceIn) return `Segment ${i + 1}: end must be after start.`;
    if (s.sourceOut - s.sourceIn < MIN_SEGMENT_S) return `Segment ${i + 1}: too short.`;
    if (s.sourceOut > sourceDuration + 0.001) return `Segment ${i + 1}: past the source video.`;
    if (s.speed < MIN_SPEED || s.speed > MAX_SPEED) return `Segment ${i + 1}: speed out of range.`;
    if (s.caption.length > MAX_TEXT_LENGTH) return `Segment ${i + 1}: caption is too long.`;
  }
  const out = timelineDuration(segments);
  for (const [j, o] of overlays.entries()) {
    if (!o.text.trim()) return `Overlay ${j + 1}: text is required.`;
    if (o.text.length > MAX_TEXT_LENGTH) return `Overlay ${j + 1}: text is too long.`;
    if (![o.startS, o.endS].every(Number.isFinite)) {
      return `Overlay ${j + 1}: values must be finite numbers.`;
    }
    if (o.startS < 0) return `Overlay ${j + 1}: start cannot be negative.`;
    if (o.endS <= o.startS) return `Overlay ${j + 1}: end must be after start.`;
    if (o.endS > out + 0.001) return `Overlay ${j + 1}: past the output (${out}s).`;
  }
  return null;
}
