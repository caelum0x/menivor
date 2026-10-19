/**
 * Typed client for the caller's uploaded source media — Expo.
 *
 * `GET /uploads` lists the caller-owned assets registered via
 * `POST /uploads/register` (newest first) with a presigned `url` for preview;
 * `DELETE /uploads/{id}` removes one. Owner-scoped server side: another
 * user's asset yields 404. Auth flows through `options.token` (x-api-key).
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

export type UploadMediaKind = "video" | "image" | "audio" | "other";

export interface UploadItem {
  id: string;
  key: string;
  kind: string;
  filename: string;
  contentType: string;
  sizeBytes: number;
  durationS: number;
  createdAt: string | null;
  /** Presigned GET URL for preview/download, when the backend could sign one. */
  url: string | null;
  /** Job that consumed this upload, when it was used in a reel. */
  jobId: string | null;
}

interface RawUpload {
  id?: string;
  asset_id?: string;
  key?: string;
  r2_key?: string;
  kind?: string;
  filename?: string;
  name?: string;
  content_type?: string;
  size_bytes?: number;
  size?: number;
  duration_s?: number;
  created_at?: string | null;
  url?: string | null;
  get_url?: string | null;
  download_url?: string | null;
  mime_type?: string;
  bytes?: number;
  job_id?: string | null;
}

function basename(key: string): string {
  const parts = key.split("/");
  return parts[parts.length - 1] || key;
}

function normalize(raw: RawUpload): UploadItem | null {
  const id = String(raw.id ?? raw.asset_id ?? "").trim();
  const key = String(raw.key ?? raw.r2_key ?? "").trim();
  if (!id) return null;
  return {
    id,
    key,
    kind: String(raw.kind ?? "upload"),
    filename: String(raw.filename ?? raw.name ?? (key ? basename(key) : id)),
    contentType: String(raw.content_type ?? raw.mime_type ?? ""),
    sizeBytes: Number(raw.size_bytes ?? raw.size ?? raw.bytes ?? 0) || 0,
    durationS: Number(raw.duration_s ?? 0) || 0,
    createdAt: raw.created_at ?? null,
    url: raw.get_url ?? raw.url ?? raw.download_url ?? null,
    jobId: raw.job_id ?? null,
  };
}

const VIDEO_EXT = /\.(mp4|mov|m4v|webm|mkv)$/i;
const IMAGE_EXT = /\.(png|jpe?g|webp|gif|heic)$/i;
const AUDIO_EXT = /\.(mp3|m4a|wav|aac|ogg|flac)$/i;

/** Classify an upload for preview + "use in Create" affordances. */
export function uploadMediaKind(item: UploadItem): UploadMediaKind {
  const ct = item.contentType.toLowerCase();
  if (ct.startsWith("video/") || VIDEO_EXT.test(item.key)) return "video";
  if (ct.startsWith("image/") || IMAGE_EXT.test(item.key)) return "image";
  if (ct.startsWith("audio/") || AUDIO_EXT.test(item.key)) return "audio";
  return "other";
}

/** Human-readable byte size (e.g. "12.4 MB"). */
export function formatBytes(bytes: number): string {
  if (!bytes || bytes < 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export async function listUploads(options?: RequestOptions): Promise<UploadItem[]> {
  const data = await request<RawUpload[] | { uploads?: RawUpload[]; items?: RawUpload[] }>(
    "/uploads?limit=100",
    { options },
  );
  const rows = Array.isArray(data)
    ? data
    : data?.uploads ?? (data as { assets?: RawUpload[] })?.assets ?? data?.items ?? [];
  return rows.map(normalize).filter((row): row is UploadItem => row !== null);
}

export function deleteUpload(
  id: string,
  options?: RequestOptions,
): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/uploads/${encodeURIComponent(id)}`, {
    method: "DELETE",
    options,
  });
}
