import type { Page } from "@/components/design/types";
import type { JobCreateRequest } from "@/lib/types";

export type Decision = "pending" | "kept" | "skipped";
export type IdeaKind = "carousel" | "reel";
export type RenderStatus = "none" | "done" | "failed" | "queued";
export type SlideSize = "tiktok" | "instagram";

export interface IdeaOutputs {
  size?: SlideSize;
  design_id?: string;
  png_keys?: string[];
  png_urls: (string | null)[];
  pdf_key?: string;
  pdf_url: string | null;
  mp4_key?: string;
  mp4_url: string | null;
  job_id?: string;
  error?: string;
  video_status?: "" | "queued" | "rendering" | "done" | "failed";
  video_error?: string;
}

export interface MonthIdea {
  id: string;
  plan_id: string;
  position: number;
  format: string;
  format_name: string;
  why: string;
  kind: IdeaKind;
  hook: string;
  slides: string[];
  script: string;
  caption: string;
  source: "llm" | "rules";
  decision: Decision;
  decided_at: string | null;
  render_status: RenderStatus;
  outputs: IdeaOutputs;
  preview: { width: number; height: number; page: Page };
  reel_job?: { body: JobCreateRequest; idempotency_key: string };
}

export interface PlanCounts {
  pending: number;
  kept: number;
  skipped: number;
  total: number;
}

export interface MonthPlanSummary {
  id: string;
  url: string;
  name: string;
  brief: { one_liner?: string; audience?: string; website?: string };
  created_at: string | null;
  counts: PlanCounts;
}

export interface MonthPlan extends MonthPlanSummary {
  ideas: MonthIdea[];
}

export interface IdeaUpdate {
  idea: MonthIdea;
  counts: PlanCounts;
}
