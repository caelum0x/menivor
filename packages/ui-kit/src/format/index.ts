/**
 * Shared formatting helpers (money/duration/percent/number) — pure, framework-
 * free, reused by web + electron so numbers render identically everywhere.
 */

/** Integer microdollars → "$0.084" (sub-10¢ uses 3 decimals). */
export function formatUsdMicros(micros: number): string {
  const usd = (micros || 0) / 1_000_000;
  const digits = usd !== 0 && Math.abs(usd) < 0.1 ? 3 : 2;
  return `$${usd.toFixed(digits)}`;
}

/** Microdollars → credits (1 credit = $0.01 = 10_000 micros). */
export function formatCredits(micros: number): string {
  return `${Math.round((micros || 0) / 10_000).toLocaleString()} credits`;
}

/** Seconds → "1:05" / "1:02:03". */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return (h > 0 ? `${h}:` : "") + `${mm}:${String(sec).padStart(2, "0")}`;
}

/** 0..1 → "84%". */
export function formatPercent(fraction: number, digits = 0): string {
  return `${(Math.max(0, Math.min(1, fraction || 0)) * 100).toFixed(digits)}%`;
}

/** 12500 → "12.5K", 3_400_000 → "3.4M". */
export function formatCompact(n: number): string {
  const v = n || 0;
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return String(v);
}
