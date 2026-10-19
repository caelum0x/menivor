/**
 * Small, pure presentation helpers for the Connections screen. Dependency-free
 * (Hermes has patchy `Intl`, so dates are formatted manually). Nothing here ever
 * touches a token — connections only ever carry the provider, account id,
 * status, scopes and timestamps.
 */

import type { SocialProvider } from "@/lib/types";

/** Human-readable label for a social provider (falls back to the raw id). */
const PROVIDER_LABELS: Readonly<Record<SocialProvider, string>> = {
  tiktok: "TikTok",
  instagram: "Instagram",
  youtube: "YouTube",
};

/** Display name for a provider, widened to `string` for forward-compatibility. */
export function providerLabel(provider: SocialProvider | string): string {
  const known = PROVIDER_LABELS[provider as SocialProvider];
  if (known) return known;
  const raw = String(provider ?? "").trim();
  if (!raw) return "Provider";
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

/** Whether a connection's stored token is stale and needs a reconnect. */
export function isExpired(status: string | null | undefined): boolean {
  return String(status ?? "").toLowerCase() === "expired";
}

/** Short human status label ("Connected" / "Reconnect needed"). */
export function statusLabel(status: string | null | undefined): string {
  return isExpired(status) ? "Reconnect needed" : "Connected";
}

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

/** Format an ISO-8601 timestamp as "Aug 13, 2026", or "" when absent/invalid. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `${MONTHS[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}`;
}

/** Trim + split a comma-separated scope string into non-empty scope tokens. */
export function parseScopes(scopes: string | null | undefined): string[] {
  return String(scopes ?? "")
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/** A compact, human label for a job in the publish picker. */
export function jobShortLabel(jobId: string): string {
  const id = String(jobId ?? "").trim();
  if (!id) return "Reel";
  return `Reel ${id.slice(0, 8)}`;
}
