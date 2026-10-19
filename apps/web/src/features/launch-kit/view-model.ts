/** Pure helpers for Launch Kit (no React, easy to test). */

import type { LaunchPlatform, PainPointDraft, PlatformStatus } from "./api";

/** "Not started" / "Submitted" / "Live". */
export function platformStatusLabel(status: PlatformStatus): string {
  if (status === "submitted") return "Submitted";
  if (status === "live") return "Live";
  return "Not started";
}

/** Clicking the status pill cycles not_started -> submitted -> live -> not_started. */
export function nextPlatformStatus(status: PlatformStatus): PlatformStatus {
  if (status === "not_started") return "submitted";
  if (status === "submitted") return "live";
  return "not_started";
}

/** Badge tone per status: neutral, informative, done. */
export function platformStatusTone(status: PlatformStatus): "outline" | "secondary" | "success" {
  if (status === "live") return "success";
  if (status === "submitted") return "secondary";
  return "outline";
}

/** Unique categories across a platform list, sorted, for a filter dropdown. */
export function categoriesFromPlatforms(platforms: readonly LaunchPlatform[]): readonly string[] {
  const set = new Set<string>();
  for (const platform of platforms) {
    for (const category of platform.categories) set.add(category);
  }
  return Array.from(set).sort();
}

/** Platforms matching `category`, or every platform when `category` is empty. */
export function filterPlatformsByCategory(
  platforms: readonly LaunchPlatform[],
  category: string,
): readonly LaunchPlatform[] {
  if (!category) return platforms;
  return platforms.filter((platform) => platform.categories.includes(category));
}

/** "3 / 18 submitted or live". */
export function platformProgressLabel(platforms: readonly LaunchPlatform[]): string {
  const done = platforms.filter((p) => p.status !== "not_started").length;
  return `${done} / ${platforms.length} submitted or live`;
}

/** "3 / 10 steps done". */
export function checklistProgressLabel(done: number, total: number): string {
  return `${done} / ${total} steps done`;
}

/** "42 upvotes · 3d old" / "42 upvotes · today". */
export function threadMeta(upvotes: number, ageDays: number): string {
  const age = ageDays <= 0 ? "today" : `${ageDays}d old`;
  return `${upvotes} upvote${upvotes === 1 ? "" : "s"} · ${age}`;
}

/** "Approved" / "Dismissed" / "Drafted" for a pain-point draft's status badge. */
export function draftStatusLabel(status: PainPointDraft["status"]): string {
  if (status === "approved") return "Approved";
  if (status === "dismissed") return "Dismissed";
  return "Drafted";
}

/** Drafts not yet acted on come first, newest first within each group. */
export function sortDrafts(drafts: readonly PainPointDraft[]): readonly PainPointDraft[] {
  const rank: Record<PainPointDraft["status"], number> = { drafted: 0, approved: 1, dismissed: 2 };
  return [...drafts].sort((a, b) => {
    if (rank[a.status] !== rank[b.status]) return rank[a.status] - rank[b.status];
    return (b.created_at ?? "").localeCompare(a.created_at ?? "");
  });
}

/** Honest backlinks state, so the UI never shows a fake "no results" for an unconfigured feature. */
export type BacklinksState = "live_data" | "configured_not_live" | "not_configured";

export function backlinksState(result: { live: boolean; configured: boolean }): BacklinksState {
  if (result.live) return "live_data";
  if (result.configured) return "configured_not_live";
  return "not_configured";
}

/** A reasonable https:// URL to show when a thread/platform link needs a target attr test hook. */
export function domainLooksValid(domain: string): boolean {
  const cleaned = domain.trim().toLowerCase();
  return cleaned.length >= 3 && cleaned.includes(".") && !cleaned.includes(" ");
}
