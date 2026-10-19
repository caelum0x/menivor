/**
 * Pure subtitle helpers for the free /tools pages: parse SRT or WebVTT into
 * cues, serialise cues back to either format, and shift every timestamp by an
 * offset. No DOM, no I/O, so the converters run client-side and are unit-tested.
 */

export interface Cue {
  readonly startMs: number;
  readonly endMs: number;
  readonly text: string;
}

export type SubtitleFormat = "srt" | "vtt";

const TIMESTAMP =
  /(?:(\d{1,3}):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})/;
const TIMING_LINE = new RegExp(
  `^\\s*${TIMESTAMP.source}\\s*-->\\s*${TIMESTAMP.source}`,
);

/** Parse "01:02:03,456", "02:03.456" or "1:02:03.4" into milliseconds. */
export function parseTimestamp(value: string): number | null {
  const match = TIMESTAMP.exec(value.trim());
  if (!match) return null;
  const [, h, m, s, frac] = match;
  const ms = Number((frac ?? "0").padEnd(3, "0"));
  return (
    Number(h ?? 0) * 3_600_000 + Number(m) * 60_000 + Number(s) * 1000 + ms
  );
}

/** Format milliseconds as HH:MM:SS,mmm (srt) or HH:MM:SS.mmm (vtt). */
export function formatTimestamp(totalMs: number, format: SubtitleFormat): string {
  const safe = Math.max(0, Math.round(totalMs));
  const h = Math.floor(safe / 3_600_000);
  const m = Math.floor((safe % 3_600_000) / 60_000);
  const s = Math.floor((safe % 60_000) / 1000);
  const ms = safe % 1000;
  const pad = (n: number, width = 2) => String(n).padStart(width, "0");
  const sep = format === "srt" ? "," : ".";
  return `${pad(h)}:${pad(m)}:${pad(s)}${sep}${pad(ms, 3)}`;
}

/** Guess the format of a subtitle file from its content. */
export function detectFormat(input: string): SubtitleFormat {
  return /^﻿?WEBVTT/.test(input.trimStart()) ? "vtt" : "srt";
}

function parseTimingLine(line: string): { startMs: number; endMs: number } | null {
  const match = TIMING_LINE.exec(line);
  if (!match) return null;
  const [startRaw, endRaw] = line.split("-->");
  const startMs = parseTimestamp(startRaw ?? "");
  const endMs = parseTimestamp(endRaw ?? "");
  if (startMs === null || endMs === null) return null;
  return { startMs, endMs };
}

/**
 * Parse SRT or WebVTT text into cues. Cue numbers, VTT identifiers, NOTE and
 * STYLE blocks and VTT cue settings are ignored; text lines are kept as-is.
 */
export function parseSubtitles(input: string): Cue[] {
  const normalized = input.replace(/^﻿/, "").replace(/\r\n?/g, "\n");
  const blocks = normalized.split(/\n{2,}/);
  const cues: Cue[] = [];
  for (const block of blocks) {
    const lines = block.split("\n").filter((line) => line.length > 0);
    const timingIndex = lines.findIndex((line) => line.includes("-->"));
    if (timingIndex < 0) continue;
    const timing = parseTimingLine(lines[timingIndex] ?? "");
    if (!timing) continue;
    const text = lines.slice(timingIndex + 1).join("\n").trim();
    cues.push({ ...timing, text });
  }
  return cues;
}

/** Serialise cues as SRT or WebVTT. */
export function serializeSubtitles(cues: readonly Cue[], format: SubtitleFormat): string {
  const body = cues
    .map((cue, index) => {
      const timing = `${formatTimestamp(cue.startMs, format)} --> ${formatTimestamp(cue.endMs, format)}`;
      return format === "srt"
        ? `${index + 1}\n${timing}\n${cue.text}`
        : `${timing}\n${cue.text}`;
    })
    .join("\n\n");
  if (format === "vtt") return `WEBVTT\n\n${body}${body ? "\n" : ""}`;
  return body ? `${body}\n` : "";
}

/** Convert subtitle text to the target format (input format auto-detected). */
export function convertSubtitles(input: string, target: SubtitleFormat): string {
  return serializeSubtitles(parseSubtitles(input), target);
}

/**
 * Shift every cue by `offsetMs` (negative = earlier). Cues that end before
 * zero are dropped; a cue straddling zero is clamped to start at zero.
 */
export function shiftCues(cues: readonly Cue[], offsetMs: number): Cue[] {
  return cues
    .map((cue) => ({
      ...cue,
      startMs: Math.max(0, cue.startMs + offsetMs),
      endMs: cue.endMs + offsetMs,
    }))
    .filter((cue) => cue.endMs > 0);
}

/**
 * Linear retime for drift (e.g. 23.976 vs 25 fps): every time t becomes
 * t * factor + offsetMs.
 */
export function scaleCues(cues: readonly Cue[], factor: number, offsetMs = 0): Cue[] {
  if (!Number.isFinite(factor) || factor <= 0) return [...cues];
  return shiftCues(
    cues.map((cue) => ({
      ...cue,
      startMs: Math.round(cue.startMs * factor),
      endMs: Math.round(cue.endMs * factor),
    })),
    offsetMs,
  );
}

/** Timed text chunk as produced by a speech-to-text model (seconds). */
export interface TimedChunk {
  readonly text: string;
  readonly start: number;
  readonly end: number | null;
}

/**
 * Turn speech-to-text chunks into readable caption cues: at most
 * `maxChars` characters per cue, never longer than `maxDurationMs`.
 * Chunks without an end time inherit the next chunk's start (or +2s).
 */
export function chunksToCues(
  chunks: readonly TimedChunk[],
  maxChars = 42,
): Cue[] {
  const cues: Cue[] = [];
  chunks.forEach((chunk, index) => {
    const text = chunk.text.replace(/\s+/g, " ").trim();
    if (!text) return;
    const startMs = Math.round(chunk.start * 1000);
    const nextStart = chunks[index + 1]?.start;
    const endSec = chunk.end ?? nextStart ?? chunk.start + 2;
    const endMs = Math.max(startMs + 300, Math.round(endSec * 1000));
    const pieces = splitText(text, maxChars);
    const span = endMs - startMs;
    const totalChars = pieces.reduce((sum, piece) => sum + piece.length, 0);
    let cursor = startMs;
    pieces.forEach((piece, pieceIndex) => {
      const isLast = pieceIndex === pieces.length - 1;
      const pieceEnd = isLast
        ? endMs
        : cursor + Math.round((span * piece.length) / totalChars);
      cues.push({ startMs: cursor, endMs: pieceEnd, text: piece });
      cursor = pieceEnd;
    });
  });
  return cues;
}

/** Split text on word boundaries into pieces of at most `maxChars`. */
export function splitText(text: string, maxChars: number): string[] {
  const words = text.split(" ").filter(Boolean);
  const pieces: string[] = [];
  let current = "";
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length > maxChars && current) {
      pieces.push(current);
      current = word;
    } else {
      current = candidate;
    }
  }
  if (current) pieces.push(current);
  return pieces;
}

/** Plain transcript (no timings) from chunks, joined into paragraphs. */
export function chunksToTranscript(chunks: readonly TimedChunk[]): string {
  return chunks
    .map((chunk) => chunk.text.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .join(" ")
    .replace(/([.!?])\s+(?=[A-Z])/g, "$1\n")
    .trim();
}
