/**
 * Story in 8 frames (MH5) API. Signed in. The plan writes the eight lines and
 * prices both versions; starting sends back the lines (edited or not) and the
 * price the user saw, so a changed price is refused, never charged.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type StoryMode = "frames" | "animated";

export interface StoryPrice {
  readonly standard_credits: number;
  readonly ai_video_credits: number;
}

export interface StoryFrame {
  readonly index: number;
  readonly beat: string;
  readonly line: string;
  readonly camera: string;
  readonly seconds: number;
  readonly image_url?: string;
  readonly identity_score?: number | null;
  readonly animated?: boolean;
}

export interface StoryPlan {
  readonly lines: readonly string[];
  readonly frames: readonly StoryFrame[];
  readonly quote: { readonly seconds: number; readonly frames: StoryPrice; readonly animated: StoryPrice };
}

export interface StoryJob {
  readonly job_id: string;
  readonly state: number;
  readonly mode: StoryMode;
  readonly stage: string;
  readonly frames: readonly StoryFrame[];
  readonly identity_score_min: number | null;
  readonly video_url: string;
  readonly poster_url: string;
  readonly error: string;
}

export interface PlanInput {
  readonly topic?: string;
  readonly script?: string;
  readonly character_id?: string | null;
}

export function planStory(body: PlanInput, options?: RequestOptions): Promise<StoryPlan> {
  return apiRequest<StoryPlan>("/film/story8/plan", { method: "POST", body, options });
}

export function startStory(
  body: { lines: readonly string[]; mode: StoryMode; quoted: StoryPrice; character_id?: string | null },
  options?: RequestOptions,
): Promise<{ job_id: string; state: number }> {
  return apiRequest<{ job_id: string; state: number }>("/film/story8", { method: "POST", body, options });
}

export function getStory(jobId: string, options?: RequestOptions): Promise<StoryJob> {
  const jid = encodeURIComponent(jobId);
  return apiRequest<StoryJob>(`/film/story8/${jid}`, { options });
}

/** Backend TASK_STATE_COMPLETE and TASK_STATE_FAILED. */
export const STORY_DONE = 1;
export const STORY_FAILED = -1;
