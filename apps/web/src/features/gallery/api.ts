/**
 * Gallery API (MH3). Reads are public and edge-cached for 30 s; publishing,
 * Recreate and remix links need the signed-in user. Money moves only through
 * the existing create routes, priced first.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import type { PresetPlan } from "@/src/features/presets-shelf/api";

export interface GalleryProvenance {
  readonly ai_generated: boolean;
  readonly content_id: string;
  readonly report_url: string;
  readonly generator: string;
}

export interface GalleryItem {
  readonly id: string;
  readonly title: string;
  readonly preset_id: string;
  readonly preset_name: string;
  readonly remix_count: number;
  readonly preview_url: string;
  readonly poster_url: string;
  readonly published_at: string | null;
  readonly recreate_url: string;
  readonly provenance: GalleryProvenance;
}

export interface RecreatePlan extends Pick<PresetPlan, "route" | "body"> {
  readonly item_id: string;
}

export interface OwnReel {
  readonly job_id: string;
  readonly state: number;
  readonly title?: string;
  readonly poster_url?: string;
}

/** Backend TASK_STATE_COMPLETE. */
export const JOB_COMPLETE = 1;

export async function listGallery(options?: RequestOptions): Promise<readonly GalleryItem[]> {
  const data = await apiRequest<{ items: GalleryItem[] }>("/gallery", { anonymous: true, options });
  return data.items ?? [];
}

export async function galleryWall(options?: RequestOptions): Promise<readonly GalleryItem[]> {
  const data = await apiRequest<{ items: GalleryItem[] }>("/gallery/wall", { anonymous: true, options });
  return data.items ?? [];
}

export function getGalleryItem(id: string, options?: RequestOptions): Promise<GalleryItem> {
  const iid = encodeURIComponent(id);
  return apiRequest<GalleryItem>(`/gallery/${iid}`, { anonymous: true, options });
}

export function publishToGallery(body: { job_id: string; title: string }, options?: RequestOptions) {
  return apiRequest<{ id: string; job_id: string }>("/gallery", { method: "POST", body, options });
}

export function unpublishFromGallery(id: string, options?: RequestOptions) {
  const iid = encodeURIComponent(id);
  return apiRequest<{ id: string }>(`/gallery/${iid}`, { method: "DELETE", options });
}

export function recreatePlan(
  id: string,
  body: { subject: string; image_key?: string },
  options?: RequestOptions,
): Promise<RecreatePlan> {
  const iid = encodeURIComponent(id);
  return apiRequest<RecreatePlan>(`/gallery/${iid}/recreate`, { method: "POST", body, options });
}

export function linkRemix(id: string, jobId: string, options?: RequestOptions) {
  const iid = encodeURIComponent(id);
  return apiRequest<{ item_id: string; job_id: string }>(`/gallery/${iid}/remixes`, {
    method: "POST",
    body: { job_id: jobId },
    options,
  });
}

export function getRemix(jobId: string, options?: RequestOptions) {
  const jid = encodeURIComponent(jobId);
  return apiRequest<{ job_id: string; item_id: string; counted: boolean }>(`/gallery/remixes/${jid}`, { options });
}

export async function listOwnFinishedReels(options?: RequestOptions): Promise<readonly OwnReel[]> {
  const data = await apiRequest<{ jobs: OwnReel[] }>("/jobs?limit=30&offset=0", { options });
  return (data.jobs ?? []).filter((job) => job.state === JOB_COMPLETE);
}
