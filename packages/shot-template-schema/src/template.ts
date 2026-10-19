/**
 * Template + slot builders, validation, and deterministic hashing (mirror of
 * `template.py`). Slot times are integer ms so the FNV-1a hash is byte-identical.
 */

import { isRole, roleIndex } from "./roles.js";

export interface SegmentSlot {
  role: string;
  t_start_ms: number;
  t_end_ms: number;
  caption_preset: string;
  transition_out: string;
}

export interface ShotTemplate {
  slug: string;
  genre: string;
  aspect: string;
  slots: SegmentSlot[];
}

export function makeSlot(
  role: string,
  tStartMs: number,
  tEndMs: number,
  opts: { caption_preset?: string; transition_out?: string } = {},
): SegmentSlot {
  return {
    role,
    t_start_ms: Math.trunc(tStartMs),
    t_end_ms: Math.trunc(tEndMs),
    caption_preset: opts.caption_preset ?? "",
    transition_out: opts.transition_out ?? "cut",
  };
}

export function makeTemplate(
  slug: string,
  genre: string,
  aspect: string,
  slots: SegmentSlot[],
): ShotTemplate {
  return { slug, genre, aspect, slots };
}

export function totalDurationMs(template: ShotTemplate): number {
  return template.slots.reduce((max, s) => Math.max(max, Math.trunc(s.t_end_ms)), 0);
}

export function validateTemplate(template: ShotTemplate): string[] {
  const errors: string[] = [];
  const slots = template.slots ?? [];
  if (slots.length === 0) {
    errors.push("template has no slots");
    return errors;
  }
  let prevEnd: number | null = null;
  let prevRoleIdx = -1;
  slots.forEach((s, i) => {
    if (!isRole(String(s.role))) {
      errors.push(`slot ${i}: unknown role ${s.role}`);
      return;
    }
    const ts = Math.trunc(s.t_start_ms);
    const te = Math.trunc(s.t_end_ms);
    if (ts < 0) errors.push(`slot ${i}: negative t_start_ms`);
    if (te <= ts) errors.push(`slot ${i}: t_end_ms must be > t_start_ms`);
    if (prevEnd !== null && ts < prevEnd) errors.push(`slot ${i}: overlaps previous slot`);
    if (prevEnd !== null && ts > prevEnd) errors.push(`slot ${i}: gap after previous slot`);
    const idx = roleIndex(String(s.role));
    if (idx < prevRoleIdx) errors.push(`slot ${i}: role ${s.role} out of narrative order`);
    prevEnd = te;
    prevRoleIdx = idx;
  });
  if (slots.length && slots[0].role !== "hook" && slots[0].role !== "loop") {
    errors.push("first slot should be a hook (or a single loop)");
  }
  return errors;
}

function canon(template: ShotTemplate): string {
  const body = template.slots
    .map(
      (s) =>
        `${s.role},${Math.trunc(s.t_start_ms)},${Math.trunc(s.t_end_ms)},` +
        `${s.caption_preset ?? ""},${s.transition_out ?? ""}`,
    )
    .join(";");
  return `${template.slug}|${template.genre}|${template.aspect}|${body}`;
}

/** Deterministic FNV-1a-32 hex — identical to the Python port. */
export function contentHash(template: ShotTemplate): string {
  let h = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(canon(template))) {
    h ^= byte;
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}
