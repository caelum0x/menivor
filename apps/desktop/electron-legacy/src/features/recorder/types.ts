/**
 * Shared types for the screen-recorder feature. The engine, the hook, and the
 * panel all import from here so the public surface stays consistent.
 */

import type { ScreenSource } from "../../../electron/ipc";
import type { MimeChoice } from "./mediaSupport";

// Re-export the bridge's source shape so consumers of this feature never need to
// reach across into the electron/ layer directly.
export type { ScreenSource };

/** Low-level engine run state, mirroring `MediaRecorder.state`. */
export type RecorderRunState = "inactive" | "recording" | "paused";

/**
 * High-level UI status surfaced by {@link useScreenRecorder}. Drives which panel
 * phase is rendered (picker → live capture → review), plus loading/error states.
 */
export type RecorderStatus =
  | "idle"
  | "acquiring"
  | "recording"
  | "paused"
  | "stopping"
  | "review"
  | "error";

/** Options for a single capture session. All fields are optional. */
export interface StartOptions {
  /**
   * Electron `desktopCapturer` source id chosen from the in-app picker. When
   * omitted, the browser-standard `getDisplayMedia` picker is used instead.
   */
  sourceId?: string;
  /** Attempt to capture an audio track alongside video (default `false`). */
  audio?: boolean;
  /** Target frame rate hint passed to the capture constraints (default `30`). */
  frameRate?: number;
  /** Upper bound on capture width in pixels (default `1920`). */
  maxWidth?: number;
  /** Upper bound on capture height in pixels (default `1080`). */
  maxHeight?: number;
  /** Override the container-negotiation preference order. */
  preferredMimeTypes?: readonly MimeChoice[];
  /**
   * Invoked when the OS ends the capture out-of-band (e.g. the user clicks the
   * system "Stop sharing" control). Consumers should finalise the recording.
   */
  onStreamEnded?: () => void;
}

/**
 * The finished recording. `file` is upload-ready — it is a `File` (a `Blob`
 * subclass), so it can be passed straight to the presign/upload flow.
 */
export interface RecordingResult {
  /** Upload-ready `File` (named, typed) — hand directly to the uploader. */
  readonly file: File;
  /** The same bytes as `file`, for callers that prefer a raw `Blob`. */
  readonly blob: Blob;
  /** Negotiated container MIME type, e.g. `video/webm;codecs=vp9`. */
  readonly mimeType: string;
  /** Total recorded bytes. */
  readonly sizeBytes: number;
  /** Recorded wall-clock duration in milliseconds (excludes paused time). */
  readonly durationMs: number;
  /** Generated filename, e.g. `screen-1699999999999.webm`. */
  readonly filename: string;
}

/** Metadata handed alongside the file when a recording is accepted. */
export interface RecordingMeta {
  readonly durationMs: number;
  readonly sizeBytes: number;
  readonly mimeType: string;
}
