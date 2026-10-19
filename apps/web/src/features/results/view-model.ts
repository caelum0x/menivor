/** Pure helpers for the Results page (no React, easy to test). */

import { findPreset } from "@/src/features/create-compose/one-flow/plan";
import type { Remake, SeriesPoint, TrackedPost } from "./api";

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

/** 12400 -> "12.4K". `null` (never reported) -> "". */
export function shortCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  return compact.format(Math.max(0, value));
}

/** The human name of a create preset / style id ("meme_hook" -> "Meme hook"). */
export function presetLabel(preset: string): string {
  if (!preset) return "";
  return findPreset(preset)?.title ?? "";
}

/** `/create` link that starts new reels from the same topic in the same style. */
export function remakeHref(remake: Remake | null | undefined): string {
  const q = (remake?.q ?? "").trim().slice(0, 600);
  if (!q) return "/create";
  const params = new URLSearchParams({ q });
  if (remake?.preset && findPreset(remake.preset)) params.set("preset", remake.preset);
  params.set("auto", "1");
  return `/create?${params.toString()}`;
}

/** One short line under a post: its numbers, or why there are none yet. */
export function postLine(post: TrackedPost): string {
  const parts: string[] = [];
  if (post.likes !== null) parts.push(`${shortCount(post.likes)} likes`);
  if (post.comments !== null) parts.push(`${shortCount(post.comments)} comments`);
  if (post.shares !== null) parts.push(`${shortCount(post.shares)} shares`);
  if (post.saves !== null) parts.push(`${shortCount(post.saves)} saves`);
  if (parts.length > 0) return parts.join(" · ");
  if (post.note) return post.note;
  return post.state === "waiting" ? "Reading the numbers..." : "";
}

export interface ChartGeometry {
  readonly line: string;
  readonly area: string;
  readonly max: number;
  readonly first: SeriesPoint;
  readonly last: SeriesPoint;
}

/** SVG path data for a views-over-time chart in a `width` x `height` box. */
export function chartGeometry(
  series: readonly SeriesPoint[],
  width: number,
  height: number,
): ChartGeometry | null {
  const first = series[0];
  const last = series[series.length - 1];
  if (series.length < 2 || !first || !last) return null;
  const max = Math.max(...series.map((p) => p.views), 1);
  const step = width / (series.length - 1);
  const pad = 6;
  const y = (v: number) => pad + (height - 2 * pad) * (1 - v / max);
  const points = series.map((p, i) => `${(i * step).toFixed(1)},${y(p.views).toFixed(1)}`);
  const line = `M${points.join(" L")}`;
  const area = `${line} L${width},${height} L0,${height} Z`;
  return { line, area, max, first, last };
}

/** "Sep 27" for an ISO date. */
export function shortDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}
