/**
 * Pure editor domain model for the standalone editor route.
 *
 * This mirrors the active product model in `../../src/features/editor` so the
 * preserved TanStack route can build the exact same non-destructive EDL that
 * the Next.js editor submits, without importing the Next.js/Clerk runtime.
 * Keep it framework-free and dependency-free — it is unit-testable in plain
 * Node and shared by the route component only.
 */

// --- Job snapshot ----------------------------------------------------------- //

/** Backend job-state integers (mirror packages/api-contract/job-state). */
export const JOB_STATE = {
  Failed: -1,
  Complete: 1,
  Processing: 4,
} as const;

/** Minimal job snapshot the editor needs (a superset is returned by the API). */
export interface EditorJob {
  job_id: string;
  state: number;
  progress: number;
  result_url?: string;
  poster_url?: string;
  cover_url?: string;
  correlation_id?: string;
  error?: string;
}

export function isTerminalState(state: number): boolean {
  return state === JOB_STATE.Complete || state === JOB_STATE.Failed;
}

export function isFailedState(state: number): boolean {
  return state === JOB_STATE.Failed;
}

/** Only ever hand a `<video>` an absolute HTTP(S) URL (no R2 credentials here). */
function toDisplayUrl(value?: string | null): string | undefined {
  if (!value) return undefined;
  const trimmed = value.trim();
  return /^https?:\/\//i.test(trimmed) ? trimmed : undefined;
}

export function jobResultUrl(job: EditorJob): string | undefined {
  return toDisplayUrl(job.result_url);
}

export function jobPosterUrl(job: EditorJob): string | undefined {
  return toDisplayUrl(job.cover_url) ?? toDisplayUrl(job.poster_url);
}

export interface EditorSource {
  jobId: string;
  progress: number;
  resultUrl?: string;
  posterUrl?: string;
  correlationId?: string;
  failed: boolean;
  terminal: boolean;
  error?: string;
}

export function mapJobToEditorSource(job: EditorJob): EditorSource {
  return {
    jobId: job.job_id,
    progress: job.progress,
    resultUrl: jobResultUrl(job),
    posterUrl: jobPosterUrl(job),
    correlationId: job.correlation_id,
    failed: isFailedState(job.state),
    terminal: isTerminalState(job.state),
    error: job.error,
  };
}

// --- Timeline (EDL) model --------------------------------------------------- //

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

/** Client-side selection of a curated background-music track (+ mix volume). */
export interface MusicSelection {
  /** Curated track slug (empty string = no background music). */
  musicId: string;
  /** Linear mix gain applied to the track, 1.0 = unity. */
  volume: number;
}

/** One entry from the real `GET /catalog/music` catalog (browser view). */
export interface MusicTrack {
  id: string;
  name: string;
  filename?: string;
  durationS?: number;
}

/** Raw catalog entry as returned by the API (snake_case, superset). */
export interface MusicCatalogEntry {
  id: string;
  name?: string;
  filename?: string;
  duration_s?: number;
}

export const MIN_SEGMENT_S = 0.1;
export const MIN_SPEED = 0.25;
export const MAX_SPEED = 4;
export const MAX_SEGMENTS = 200;
export const MAX_OVERLAYS = 50;
export const MAX_TEXT_LENGTH = 200;
export const MIN_MUSIC_VOLUME = 0;
export const MAX_MUSIC_VOLUME = 2;

/** Mirrors the server `_MUSIC_ID_PATTERN`: lowercase `[a-z0-9]` slug, hyphen-joined. */
export const MUSIC_ID_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

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

export function newMusicSelection(): MusicSelection {
  return { musicId: "", volume: 1 };
}

/** Clamp a mix volume into the accepted `[MIN_MUSIC_VOLUME, MAX_MUSIC_VOLUME]` range. */
export function clampMusicVolume(volume: number): number {
  if (!Number.isFinite(volume)) return 1;
  return Math.min(MAX_MUSIC_VOLUME, Math.max(MIN_MUSIC_VOLUME, volume));
}

/** Whether a music track is actually selected (non-empty, well-formed slug). */
export function hasMusic(music: MusicSelection | null | undefined): boolean {
  return Boolean(music && MUSIC_ID_PATTERN.test(music.musicId.trim()));
}

/** Normalize a raw catalog payload into the browser `MusicTrack` view. */
export function mapMusicCatalog(entries: readonly MusicCatalogEntry[]): MusicTrack[] {
  const tracks: MusicTrack[] = [];
  for (const entry of entries) {
    const id = typeof entry?.id === "string" ? entry.id.trim() : "";
    if (!id) continue;
    tracks.push({
      id,
      name: entry.name && entry.name.trim() ? entry.name.trim() : id,
      filename: entry.filename,
      durationS:
        typeof entry.duration_s === "number" && Number.isFinite(entry.duration_s)
          ? entry.duration_s
          : undefined,
    });
  }
  return tracks;
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

/** Immutably move a segment one slot up (-1) or down (+1); clamps at the ends. */
export function moveSegment(
  segments: readonly TimelineSegment[],
  id: string,
  direction: -1 | 1,
): TimelineSegment[] {
  const index = segments.findIndex((s) => s.id === id);
  if (index < 0) return [...segments];
  const target = index + direction;
  if (target < 0 || target >= segments.length) return [...segments];
  const next = [...segments];
  const [moved] = next.splice(index, 1);
  next.splice(target, 0, moved);
  return next;
}

/**
 * Immutably move the segment identified by `id` to `toIndex` (drag-and-drop
 * reorder). The target index is clamped into range; a no-op returns a copy.
 */
export function moveSegmentToIndex(
  segments: readonly TimelineSegment[],
  id: string,
  toIndex: number,
): TimelineSegment[] {
  const from = segments.findIndex((s) => s.id === id);
  if (from < 0) return [...segments];
  const clamped = Math.max(0, Math.min(segments.length - 1, Math.trunc(toIndex)));
  if (from === clamped) return [...segments];
  const next = [...segments];
  const [moved] = next.splice(from, 1);
  next.splice(clamped, 0, moved);
  return next;
}

export function formatTimecode(seconds: number): string {
  const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const minutes = Math.floor(safe / 60);
  const remaining = safe - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${remaining.toFixed(2).padStart(5, "0")}`;
}

/** Return a human-readable validation error, or null when the EDL is valid. */
export function validateTimeline(
  segments: readonly TimelineSegment[],
  overlays: readonly TextOverlay[],
  sourceDuration: number,
  music?: MusicSelection | null,
): string | null {
  if (!Number.isFinite(sourceDuration) || sourceDuration <= 0) {
    return "Wait for the source video metadata.";
  }
  if (segments.length === 0) return "Add at least one segment.";
  if (segments.length > MAX_SEGMENTS) return `Use at most ${MAX_SEGMENTS} segments.`;
  if (overlays.length > MAX_OVERLAYS) return `Use at most ${MAX_OVERLAYS} overlays.`;
  for (const [i, s] of segments.entries()) {
    if (![s.sourceIn, s.sourceOut, s.speed].every(Number.isFinite)) {
      return `Clip ${i + 1}: values must be finite numbers.`;
    }
    if (s.sourceIn < 0) return `Clip ${i + 1}: start cannot be negative.`;
    if (s.sourceOut <= s.sourceIn) return `Clip ${i + 1}: end must be after start.`;
    if (s.sourceOut - s.sourceIn < MIN_SEGMENT_S) return `Clip ${i + 1}: too short.`;
    if (s.sourceOut > sourceDuration + 0.001) return `Clip ${i + 1}: past the source video.`;
    if (s.speed < MIN_SPEED || s.speed > MAX_SPEED) return `Clip ${i + 1}: speed out of range.`;
    if (s.caption.length > MAX_TEXT_LENGTH) return `Clip ${i + 1}: caption is too long.`;
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
  if (music && music.musicId.trim()) {
    if (!MUSIC_ID_PATTERN.test(music.musicId.trim())) {
      return "Music: pick a track from the library.";
    }
    if (!Number.isFinite(music.volume)) return "Music: volume must be a number.";
    if (music.volume < MIN_MUSIC_VOLUME || music.volume > MAX_MUSIC_VOLUME) {
      return `Music: volume must be between ${MIN_MUSIC_VOLUME} and ${MAX_MUSIC_VOLUME}.`;
    }
  }
  return null;
}

/** Serialize the client EDL into the exact POST /jobs/{id}/timeline-exports body. */
export interface TimelineExportBody {
  segments: {
    source_in: number;
    source_out: number;
    speed?: number;
    caption?: string | null;
  }[];
  overlays: {
    text: string;
    start_s: number;
    end_s: number;
    position: OverlayPosition;
  }[];
  music?: {
    music_id: string;
    volume: number;
  };
}

export function toTimelineExportBody(
  segments: readonly TimelineSegment[],
  overlays: readonly TextOverlay[],
  music?: MusicSelection | null,
): TimelineExportBody {
  const body: TimelineExportBody = {
    segments: segments.map((s) => ({
      source_in: Number(s.sourceIn.toFixed(3)),
      source_out: Number(s.sourceOut.toFixed(3)),
      speed: Number(s.speed.toFixed(3)),
      caption: s.caption.trim() || null,
    })),
    overlays: overlays.map((o) => ({
      text: o.text.trim(),
      start_s: Number(o.startS.toFixed(3)),
      end_s: Number(o.endS.toFixed(3)),
      position: o.position,
    })),
  };
  if (hasMusic(music) && music) {
    body.music = {
      music_id: music.musicId.trim(),
      volume: Number(clampMusicVolume(music.volume).toFixed(3)),
    };
  }
  return body;
}
