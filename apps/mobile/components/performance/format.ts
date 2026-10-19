/**
 * Small, pure formatting + parsing helpers for the Hook Performance surfaces.
 * Kept dependency-free and defensive: every helper tolerates NaN/undefined so a
 * partial backend row or a half-typed input never throws or renders "NaN".
 */

/** Format a non-negative win_score with one decimal (e.g. 12.34 -> "12.3"). */
export function formatScore(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0.0";
  return value.toFixed(1);
}

/** Format a retention/percentage value as a whole percent (e.g. 82.4 -> "82%"). */
export function formatPct(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0%";
  return `${Math.round(Math.min(100, value))}%`;
}

/**
 * Parse a free-text count field into a non-negative integer, or `undefined`
 * when the field is empty (so an untouched field is simply not sent). Strips any
 * non-digit characters and never returns a negative number.
 */
export function parseCount(text: string): number | undefined {
  const digits = text.replace(/[^0-9]/g, "");
  if (digits.length === 0) return undefined;
  const n = Number.parseInt(digits, 10);
  return Number.isFinite(n) && n >= 0 ? n : undefined;
}

/**
 * Parse a free-text retention field into a number clamped to [0,100], or
 * `undefined` when the field is empty.
 */
export function parseRetention(text: string): number | undefined {
  const trimmed = text.trim();
  if (trimmed.length === 0) return undefined;
  const n = Number.parseFloat(trimmed);
  if (!Number.isFinite(n)) return undefined;
  return Math.max(0, Math.min(100, n));
}
