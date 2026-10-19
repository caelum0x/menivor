/** Per-platform publish caps + validation (mirror of `caps.py`). */

export type Platform = "tiktok" | "instagram" | "youtube" | "x";
export const PLATFORMS: Platform[] = ["tiktok", "instagram", "youtube", "x"];

export interface PlatformCaps {
  min_duration_s: number;
  max_duration_s: number;
  aspects: string[];
  daily_cap: number;
  caption_max: number;
  formats: string[];
}

export const CAPS: Record<string, PlatformCaps> = {
  tiktok: { min_duration_s: 3, max_duration_s: 600, aspects: ["9:16"], daily_cap: 15, caption_max: 2200, formats: ["mp4"] },
  instagram: { min_duration_s: 3, max_duration_s: 90, aspects: ["9:16", "1:1", "4:5"], daily_cap: 50, caption_max: 2200, formats: ["mp4", "mov"] },
  youtube: { min_duration_s: 1, max_duration_s: 180, aspects: ["9:16"], daily_cap: 100, caption_max: 100, formats: ["mp4", "mov"] },
  x: { min_duration_s: 1, max_duration_s: 140, aspects: ["9:16", "16:9", "1:1"], daily_cap: 1000, caption_max: 280, formats: ["mp4"] },
};

export function capsFor(platform: string): PlatformCaps | undefined {
  return CAPS[String(platform || "").trim().toLowerCase()];
}

export interface PublishCheck {
  duration_s: number;
  aspect: string;
  caption_len: number;
  fmt?: string;
}

/** Reject an out-of-spec post before upload. Empty array = OK. */
export function validatePublish(platform: string, check: PublishCheck): string[] {
  const c = capsFor(platform);
  if (!c) return [`unknown platform ${platform}`];
  const { duration_s, aspect, caption_len } = check;
  const fmt = check.fmt ?? "mp4";
  const errors: string[] = [];
  if (duration_s < c.min_duration_s) errors.push(`${platform}: duration ${duration_s}s below min ${c.min_duration_s}s`);
  if (duration_s > c.max_duration_s) errors.push(`${platform}: duration ${duration_s}s over max ${c.max_duration_s}s`);
  if (!c.aspects.includes(aspect)) errors.push(`${platform}: aspect ${aspect} not in ${jsonList(c.aspects)}`);
  if (caption_len > c.caption_max) errors.push(`${platform}: caption ${caption_len} chars over max ${c.caption_max}`);
  if (!c.formats.includes(fmt.toLowerCase())) errors.push(`${platform}: format ${fmt} not in ${jsonList(c.formats)}`);
  return errors;
}

// Match Python list repr `['a', 'b']` so error strings are byte-identical.
function jsonList(items: string[]): string {
  return `[${items.map((s) => `'${s}'`).join(", ")}]`;
}

export function remainingDaily(platform: string, postedToday: number): number {
  const c = capsFor(platform);
  if (!c) return 0;
  return Math.max(0, c.daily_cap - Math.max(0, Math.trunc(postedToday)));
}
