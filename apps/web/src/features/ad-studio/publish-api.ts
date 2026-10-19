/**
 * Ad Studio "Publish and test" client: finished ads -> scheduled posts on the
 * creator's own accounts -> the 48h winner loop -> results and "Remake winner".
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type TestPlatform = "tiktok" | "instagram" | "youtube";
export type TestMode = "publish" | "manual";

export interface PlatformReadiness {
  platform: TestPlatform;
  label: string;
  connected: boolean;
  daily_cap: number;
  min_gap_hours: number;
  /** Days the eligible ads need at this platform's daily cap. */
  days_needed: number;
}

export interface PublishReadiness {
  publishing: { enabled: boolean; mode: string; pilot: boolean; reason: string };
  pro: { status: "active" | "required" | "unavailable" | "skipped"; reason: string };
  platforms: PlatformReadiness[];
  can_publish: boolean;
  can_track_manually: boolean;
  /** The first reason direct publishing is unavailable ('' when it is). */
  blocker: string;
}

export interface TestPost {
  platform: TestPlatform;
  status: "pending" | "publishing" | "processing" | "published" | "failed" | "canceled" | string;
  scheduled_at: string | null;
  url: string | null;
  error: string | null;
}

export interface TestMetrics {
  views: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  saves: number | null;
  engagement_rate: number | null;
  /** null = the platform did not report it (not 0%). */
  avg_watch_frac: number | null;
  completion_rate: number | null;
  rewatch_rate: number | null;
  source: "platform" | "logged" | "none" | null;
}

export interface LoggedResult {
  platform: string;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  saves: number;
  retention_pct: number;
  logged_at: string | null;
}

export interface TestAd {
  variant_id: string;
  job_id: string;
  angle_label: string;
  format: string;
  aspect: string;
  hook: string;
  poster_url: string | null;
  is_winner: boolean;
  rank: number | null;
  score: number | null;
  metrics: TestMetrics | null;
  logged: LoggedResult | null;
  posts: TestPost[];
}

export interface AdTest {
  batch_id: string;
  mode: TestMode;
  platforms: TestPlatform[];
  started_at: string | null;
  status: string;
  status_label: string;
  stopped: boolean;
  note: string;
  check_after_hours: number | null;
  check_due_at: string | null;
  last_checked_at: string | null;
  checks: number;
  early_read: boolean;
  conclusive: boolean;
  winner_variant_id: string | null;
  can_remake: boolean;
  explanation: { headline: string; reasons: string[]; caveats: string[]; confidence: string } | null;
  remake: { variant_ids: string[]; hooks: string[] } | null;
  ads: TestAd[];
}

export interface TestsPayload {
  readiness: PublishReadiness;
  eligible_variant_ids: string[];
  min_ads: number;
  max_ads: number;
  tests: AdTest[];
}

export interface StartTestInput {
  mode: TestMode;
  platforms: TestPlatform[];
  variant_ids: string[];
}

export interface LogResultInput {
  platform: string;
  views: number;
  likes?: number;
  comments?: number;
  shares?: number;
  saves?: number;
  retention_pct?: number;
}

const tests = (projectId: string) => `/ad-studio/projects/${encodeURIComponent(projectId)}/tests`;
const test = (projectId: string, batchId: string) => `${tests(projectId)}/${encodeURIComponent(batchId)}`;

export function getTests(projectId: string, options?: RequestOptions): Promise<TestsPayload> {
  return apiRequest<TestsPayload>(tests(projectId), { options });
}

export function startTest(
  projectId: string,
  body: StartTestInput,
  options?: RequestOptions,
): Promise<TestsPayload & { batch_id: string; loop_note: string }> {
  return apiRequest(tests(projectId), { method: "POST", body, options });
}

export function checkTest(projectId: string, batchId: string, options?: RequestOptions): Promise<TestsPayload> {
  return apiRequest<TestsPayload>(`${test(projectId, batchId)}/check`, { method: "POST", options });
}

export function stopTest(
  projectId: string,
  batchId: string,
  options?: RequestOptions,
): Promise<TestsPayload & { canceled_posts: number }> {
  return apiRequest(`${test(projectId, batchId)}/stop`, { method: "POST", options });
}

export function remakeWinner(
  projectId: string,
  batchId: string,
  acceptLowConfidence: boolean,
  options?: RequestOptions,
): Promise<{ variant_ids: string[]; hooks: string[]; replayed: boolean }> {
  return apiRequest(`${test(projectId, batchId)}/remake`, {
    method: "POST",
    body: { accept_low_confidence: acceptLowConfidence },
    options,
  });
}

/** Manual tests: log what one ad earned (the loop ranks from these numbers). */
export function logResult(jobId: string, body: LogResultInput, options?: RequestOptions): Promise<unknown> {
  return apiRequest(`/jobs/${encodeURIComponent(jobId)}/performance`, { method: "POST", body, options });
}

export const PLATFORM_LABEL: Record<string, string> = {
  tiktok: "TikTok",
  instagram: "Instagram",
  youtube: "YouTube",
};

/** "62%" for a 0..1 ratio; "not measured" when the platform did not report it. */
export function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "not measured" : `${Math.round(value * 1000) / 10}%`;
}

export function when(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
