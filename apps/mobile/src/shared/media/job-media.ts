/**
 * Helpers for turning a Job's media references into player-usable URLs.
 *
 * The React Native / Expo mirror of web/lib/job-media.ts. The backend exposes
 * `result_url` as a presigned URL and (Creator Studio, Phase 6) `poster_key` /
 * `preview_key` for a generated thumbnail + short teaser clip. Those may arrive
 * already presigned to an absolute URL. The device has no R2 credentials, so a
 * bare object key cannot be resolved client-side — we only ever hand a value
 * that is already an absolute HTTP(S) URL to <Image>/<Video>, and otherwise
 * degrade gracefully (placeholder / fall back to the result).
 */

import type { Job } from "@/lib/types";

/** Returns `value` only when it is a usable absolute media URL, else undefined. */
export function toDisplayUrl(value?: string | null): string | undefined {
  if (!value) return undefined;
  const trimmed = value.trim();
  return /^https?:\/\//i.test(trimmed) ? trimmed : undefined;
}

/** Signed poster/thumbnail URL for a job. */
export function jobPosterUrl(
  job: Pick<Job, "poster_url" | "poster_key">,
): string | undefined {
  return toDisplayUrl(job.poster_url) ?? toDisplayUrl(job.poster_key);
}

/** Signed short preview-clip URL for a job. */
export function jobPreviewUrl(
  job: Pick<Job, "preview_url" | "preview_key">,
): string | undefined {
  return toDisplayUrl(job.preview_url) ?? toDisplayUrl(job.preview_key);
}

/** Presigned final-result video URL for a job, when present. */
export function jobResultUrl(job: Pick<Job, "result_url">): string | undefined {
  return toDisplayUrl(job.result_url);
}

/** Signed generated cover/thumbnail image URL for a job. */
export function jobCoverUrl(
  job: Pick<Job, "cover_url" | "cover_key">,
): string | undefined {
  return toDisplayUrl(job.cover_url) ?? toDisplayUrl(job.cover_key);
}
