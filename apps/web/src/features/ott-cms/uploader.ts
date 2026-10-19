/**
 * Resumable multipart upload straight to R2 (MV2). The API only hands out part
 * URLs; the bytes never pass through it. Finished parts (number and ETag) are
 * saved per file, so a reload or a dropped connection resumes where it stopped.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface UploadStart {
  readonly key: string;
  readonly upload_id: string;
  readonly part_size: number;
  readonly parts: number;
}

export interface DonePart {
  readonly PartNumber: number;
  readonly ETag: string;
}

export interface SavedUpload extends UploadStart {
  readonly fingerprint: string;
  readonly done: readonly DonePart[];
}

export interface UploadDeps {
  readonly store?: Pick<Storage, "getItem" | "setItem" | "removeItem">;
  readonly putPart?: (url: string, blob: Blob) => Promise<string>;
  readonly onProgress?: (fraction: number) => void;
  readonly options?: RequestOptions;
  /** The file's length, so the server can check the encoding quota before any byte is sent. */
  readonly seconds?: number;
}

const PREFIX = "menivor.ott.upload.";
const URL_BATCH = 50;

export function fingerprint(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

async function defaultPut(url: string, blob: Blob): Promise<string> {
  const response = await fetch(url, { method: "PUT", body: blob });
  if (!response.ok) throw new Error(`part upload failed (${response.status})`);
  const etag = response.headers.get("ETag") ?? response.headers.get("etag") ?? "";
  if (!etag) throw new Error("the storage did not confirm a part");
  return etag;
}

export function startUpload(file: File, options?: RequestOptions, seconds?: number) {
  const body: Record<string, unknown> = { filename: file.name, size_bytes: file.size, content_type: file.type || "video/mp4" };
  if (seconds && Number.isFinite(seconds) && seconds > 0) body.seconds = seconds;
  return apiRequest<UploadStart>("/ott/uploads", { method: "POST", body, options });
}

export interface UploadCheckView {
  readonly decision: "pending" | "pass" | "hold" | "block";
  readonly reasons: readonly string[];
}

export function partUrls(key: string, uploadId: string, partNumbers: readonly number[], options?: RequestOptions) {
  return apiRequest<{ urls: Record<string, string> }>("/ott/uploads/parts", {
    method: "POST",
    body: { key, upload_id: uploadId, part_numbers: partNumbers },
    options,
  });
}

export function completeUpload(
  body: {
    key: string; upload_id: string; parts: readonly DonePart[]; title: string; kind: string; seconds: number;
    short_side: number; size_bytes?: number;
  },
  options?: RequestOptions,
) {
  return apiRequest<{ title_id: string; job: { lane: string; status: string }; check?: UploadCheckView }>("/ott/uploads/complete", {
    method: "POST",
    body,
    options,
  });
}

/** Uploads every missing part of ``file`` and returns the finished upload (resuming a saved one). */
export async function uploadFile(file: File, deps: UploadDeps = {}): Promise<SavedUpload> {
  const store = deps.store ?? globalThis.localStorage;
  const put = deps.putPart ?? defaultPut;
  const id = PREFIX + fingerprint(file);
  const saved = store?.getItem(id);
  let state: SavedUpload = saved
    ? (JSON.parse(saved) as SavedUpload)
    : { ...(await startUpload(file, deps.options, deps.seconds)), fingerprint: fingerprint(file), done: [] };
  store?.setItem(id, JSON.stringify(state));
  const doneNumbers = new Set(state.done.map((p) => p.PartNumber));
  const missing = Array.from({ length: state.parts }, (_, i) => i + 1).filter((n) => !doneNumbers.has(n));
  for (let start = 0; start < missing.length; start += URL_BATCH) {
    const batch = missing.slice(start, start + URL_BATCH);
    const { urls } = await partUrls(state.key, state.upload_id, batch, deps.options);
    for (const n of batch) {
      const blob = file.slice((n - 1) * state.part_size, Math.min(file.size, n * state.part_size));
      const etag = await put(urls[String(n)] ?? "", blob);
      state = { ...state, done: [...state.done, { PartNumber: n, ETag: etag }] };
      store?.setItem(id, JSON.stringify(state));
      deps.onProgress?.(state.done.length / state.parts);
    }
  }
  return state;
}

export function forgetUpload(file: File, store: Pick<Storage, "removeItem"> | undefined = globalThis.localStorage) {
  store?.removeItem(PREFIX + fingerprint(file));
}
