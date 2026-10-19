/**
 * Remake-winner loop contracts: mirrors apps/api/app/domains/insights
 * (winner_loop_router.py) and apps/web/src/features/insights/types.ts.
 */

export type LoopMode = "off" | "manual" | "auto";
export type LoopPlatform = "tiktok" | "instagram" | "youtube";

export const LOOP_PLATFORMS: readonly LoopPlatform[] = [
  "tiktok",
  "instagram",
  "youtube",
] as const;

export type LoopStatus =
  | "not_configured"
  | "awaiting_render"
  | "publishing"
  | "waiting_for_posts"
  | "live"
  | "measuring"
  | "winner_ready"
  | "remaking"
  | "remade"
  | "cap_reached"
  | "inconclusive";

export interface LoopSummary {
  batch_id: string;
  title: string;
  generation: number;
  root_batch_id: string;
  parent_batch_id: string;
  mode: LoopMode;
  status: LoopStatus;
  note: string;
  platforms: LoopPlatform[];
  variant_count: number;
  check_due_at: string | null;
  last_checked_at: string | null;
  winner_job_id: string;
  winner_hook: string;
  winner_views: number | null;
  winner_avg_watch_frac: number | null;
  winner_engagement_rate: number | null;
  conclusive: boolean;
  headline: string;
  confidence: "high" | "low" | "none";
  leader_job_id: string;
  remake_batch_id: string;
  updated_at: string | null;
}

export interface LoopCandidate {
  batch_id: string;
  title: string;
  variant_count: number;
  complete_count: number;
  created_at: string | null;
}

export interface LoopBoard {
  winners: LoopSummary[];
  loops: LoopSummary[];
  candidates: LoopCandidate[];
  publishing_enabled: boolean;
  job_cost_credits: number;
  remake_cost_credits: number;
}

export interface PostMetrics {
  platform: string;
  external_id: string;
  available: boolean;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  saves: number;
  avg_watch_frac: number | null;
  /** null = the platform did not report it (not measured). */
  completion_rate?: number | null;
  /** null = the platform did not report it (not measured). */
  rewatch_rate?: number | null;
  url: string;
  note: string;
}

export interface LoopVariant {
  job_id: string;
  title: string;
  hook: string;
  state: string;
  rank: number | null;
  score: number | null;
  source: "platform" | "logged" | "none";
  views: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  saves: number | null;
  engagement_rate: number | null;
  avg_watch_frac: number | null;
  /** View-weighted; null = no platform reported it (not measured). */
  completion_rate?: number | null;
  /** View-weighted; null = no platform reported it (not measured). */
  rewatch_rate?: number | null;
  posted_at: string | null;
  posts: PostMetrics[];
  is_winner: boolean;
}

export interface ExplanationReason {
  metric: "retention" | "views" | "engagement_rate";
  winner: number;
  others_avg: number;
  text: string;
}

export interface ExplanationDifference {
  aspect: string;
  winner: string;
  others: string[];
  text: string;
}

export interface WinExplanation {
  headline: string;
  reasons: ExplanationReason[];
  differences: ExplanationDifference[];
  caveats: string[];
  confidence: "high" | "low" | "none";
}

export interface LineageEntry {
  batch_id: string;
  generation: number;
  status: LoopStatus | "";
  winner_job_id: string;
  current: boolean;
}

export interface TimelineItem {
  at: string | null;
  kind: string;
  message: string;
  batch_id: string;
  job_id: string;
  platform: string;
  url: string;
}

export interface LoopDetail {
  batch_id: string;
  title: string;
  configured: boolean;
  mode: LoopMode;
  platforms: LoopPlatform[];
  spend_cap_credits: number;
  spent_credits: number;
  check_after_hours: number | null;
  min_views: number | null;
  status: LoopStatus;
  note: string;
  generation: number;
  root_batch_id: string;
  parent_batch_id: string;
  check_due_at: string | null;
  last_post_at: string | null;
  last_checked_at: string | null;
  checks: number;
  early_read: boolean;
  winner_job_id: string;
  conclusive: boolean;
  ranking_reason: string;
  uses_retention: boolean;
  explanation: WinExplanation | null;
  remake_batch_id: string;
  remake_hooks: string[];
  variants: LoopVariant[];
  lineage: LineageEntry[];
  timeline: TimelineItem[];
  publishing_enabled: boolean;
  job_cost_credits: number;
  remake_cost_credits: number;
}

export interface LoopConfigInput {
  mode: LoopMode;
  platforms: LoopPlatform[];
  spend_cap_credits?: number;
  check_after_hours?: number;
  min_views?: number;
}

export interface RemakeResult {
  batch_id: string;
  job_ids: string[];
  hooks: string[];
  credits: number;
  enqueue_failures: string[];
  replayed: boolean;
}
