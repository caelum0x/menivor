/**
 * Small, pure display helpers shared by the creator profile + leaderboard UI.
 * They only ever read SAFE public fields (handle / display_name + public
 * aggregates) — never any private datum — so they are safe to use on every
 * public surface.
 */

/** Identity subset shared by {@link CreatorProfile} and {@link LeaderboardEntry}. */
export interface CreatorIdentity {
  handle: string;
  display_name: string;
}

/** Primary label for a creator: display name → "@handle" → generic fallback. */
export function creatorTitle(identity: CreatorIdentity): string {
  const name = (identity.display_name || "").trim();
  if (name) return name;
  const handle = (identity.handle || "").trim();
  if (handle) return `@${handle}`;
  return "Creator";
}

/**
 * Secondary label ("@handle") shown under the title — blank when the handle is
 * unset or would just duplicate the title.
 */
export function creatorSubtitle(identity: CreatorIdentity): string {
  const handle = (identity.handle || "").trim();
  if (!handle) return "";
  const name = (identity.display_name || "").trim();
  return name ? `@${handle}` : "";
}

/** Compact count, e.g. 1200 → "1.2k", 3_400_000 → "3.4M". Non-finite → "0". */
export function formatCompact(value: number): string {
  if (!Number.isFinite(value)) return "0";
  const abs = Math.abs(value);
  if (abs >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`;
  }
  if (abs >= 1_000) {
    return `${(value / 1_000).toFixed(abs >= 10_000 ? 0 : 1)}k`;
  }
  return `${Math.round(value)}`;
}

/** Rating in [0,5] as one decimal, or an em dash when never rated. */
export function formatRating(value: number): string {
  return Number.isFinite(value) && value > 0 ? value.toFixed(1) : "—";
}
