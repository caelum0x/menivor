/** Content Month API client (website -> a month of posts -> swipe -> render). */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import { createJob } from "@/lib/api";

import type { Decision, IdeaUpdate, MonthIdea, MonthPlan, MonthPlanSummary, SlideSize } from "./types";

export function listPlans(options?: RequestOptions) {
  return apiRequest<{ plans: MonthPlanSummary[] }>("/month/plans", { options });
}

export function createPlan(url: string, options?: RequestOptions) {
  return apiRequest<MonthPlan>("/month/plans", { method: "POST", body: { url }, options });
}

export function getPlan(id: string, options?: RequestOptions) {
  return apiRequest<MonthPlan>(`/month/plans/${encodeURIComponent(id)}`, { options });
}

export function deletePlan(id: string, options?: RequestOptions) {
  return apiRequest<{ deleted: boolean }>(`/month/plans/${encodeURIComponent(id)}`, { method: "DELETE", options });
}

export function decideIdea(id: string, decision: Decision, options?: RequestOptions) {
  return apiRequest<IdeaUpdate>(`/month/ideas/${encodeURIComponent(id)}/decision`, {
    method: "POST",
    body: { decision },
    options,
  });
}

export function editIdea(
  id: string,
  body: { hook?: string; slides?: string[]; caption?: string },
  options?: RequestOptions,
) {
  return apiRequest<IdeaUpdate>(`/month/ideas/${encodeURIComponent(id)}`, { method: "PATCH", body, options });
}

export function renderCarousel(id: string, size: SlideSize, options?: RequestOptions) {
  return apiRequest<IdeaUpdate>(`/month/ideas/${encodeURIComponent(id)}/render`, {
    method: "POST",
    body: { size, video: true },
    options,
  });
}

export function retryVideo(id: string, options?: RequestOptions) {
  return apiRequest<IdeaUpdate>(`/month/ideas/${encodeURIComponent(id)}/video`, { method: "POST", options });
}

export function attachJob(id: string, jobId: string, options?: RequestOptions) {
  return apiRequest<IdeaUpdate>(`/month/ideas/${encodeURIComponent(id)}/job`, {
    method: "POST",
    body: { job_id: jobId },
    options,
  });
}

/** Send a kept reel idea to the reel pipeline (normal credits apply), then link the job. */
export async function makeReel(idea: MonthIdea, options?: RequestOptions): Promise<IdeaUpdate> {
  if (!idea.reel_job) throw new Error("This post is not a reel.");
  const job = await createJob(idea.reel_job.body, { ...options, idempotencyKey: idea.reel_job.idempotency_key });
  return attachJob(idea.id, job.job_id, options);
}
