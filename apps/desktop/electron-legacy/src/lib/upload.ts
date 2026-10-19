/**
 * Upload flow for the ReelForge Desktop renderer.
 *
 * A recorded screen-capture Blob is uploaded in two steps, mirroring the web
 * client's `presignAndUpload`:
 *   1. POST /uploads/presign (proxied through main) to obtain a short-lived
 *      presigned R2 `upload_url`, the exact signed `headers` to echo, and the
 *      final object `key`.
 *   2. PUT the raw bytes straight to R2 at `upload_url`. This is the ONLY direct
 *      network call the renderer makes — it carries no API secret (the presigned
 *      URL is itself the capability), so it does not need to go through main.
 *
 * The returned `key` is what callers pass as `ReelForgeParams.screen_recording_key`
 * (or `voiceover_key` / image keys) when creating a job.
 */

import { presign } from "./api";

/** Result of a completed presign + PUT upload. */
export interface UploadResult {
  /** R2 object key — use as `screen_recording_key` when creating a job. */
  key: string;
  /** Presigned GET URL for previewing the just-uploaded object. */
  get_url: string;
}

/** Progress callback: receives a 0..1 fraction of the upload lifecycle. */
export type UploadProgress = (fraction: number) => void;

/**
 * Presigns an upload for `blob`, PUTs the bytes to the returned `upload_url`
 * echoing the signed `headers`, and returns the object key. `onProgress` receives
 * a 0..1 fraction (0 after presign completes, 1 after the PUT succeeds).
 *
 * Validates the inputs at this boundary (non-empty blob, non-empty filename) so a
 * malformed recording never reaches the presign endpoint.
 */
export async function presignAndUpload(
  blob: Blob,
  filename: string,
  onProgress?: UploadProgress,
): Promise<UploadResult> {
  const cleanName = filename.trim();
  if (!cleanName) {
    throw new Error("Upload failed: a non-empty filename is required.");
  }
  if (!(blob instanceof Blob) || blob.size === 0) {
    throw new Error("Upload failed: the recording is empty.");
  }

  const contentType = blob.type || "application/octet-stream";
  const presigned = await presign({
    filename: cleanName,
    content_type: contentType,
    size: blob.size,
  });

  onProgress?.(0);

  // Echo the exact signed headers R2 expects; fall back to Content-Type only when
  // the backend returned none.
  const headers =
    presigned.headers && Object.keys(presigned.headers).length > 0
      ? presigned.headers
      : { "Content-Type": contentType };

  let putRes: Response;
  try {
    putRes = await fetch(presigned.upload_url, {
      method: "PUT",
      headers,
      body: blob,
    });
  } catch (err) {
    throw new Error(
      `Failed to upload recording to storage: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }

  if (!putRes.ok) {
    throw new Error(
      `Storage rejected the upload (${putRes.status} ${putRes.statusText}).`,
    );
  }

  onProgress?.(1);
  return { key: presigned.key, get_url: presigned.get_url };
}
