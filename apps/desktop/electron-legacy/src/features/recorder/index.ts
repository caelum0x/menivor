/**
 * Public API for the screen-recorder feature.
 *
 * Three layers, pick what you need:
 *  - {@link RecorderPanel} — drop-in UI (source picker → capture → review).
 *  - {@link useScreenRecorder} — React hook for a custom UI.
 *  - {@link ScreenRecorder} / {@link createScreenRecorder} — the imperative engine.
 *
 * The minimal contract is **`start()` → `stop(): Promise<File>`**: begin a
 * capture, then resolve an upload-ready `File`.
 */

import { ScreenRecorder } from "./ScreenRecorder";
import type { StartOptions } from "./types";

// UI + hook
export { RecorderPanel } from "./RecorderPanel";
export type { RecorderPanelProps } from "./RecorderPanel";
export { useScreenRecorder } from "./useScreenRecorder";
export type { UseScreenRecorder } from "./useScreenRecorder";

// Engine
export { ScreenRecorder } from "./ScreenRecorder";

// Source enumeration / acquisition
export { listScreenSources, acquireStream } from "./captureSources";

// Support + formatting utilities
export { isRecordingSupported, pickSupportedMimeType } from "./mediaSupport";
export type { MimeChoice } from "./mediaSupport";
export { formatBytes, formatDuration } from "./format";

// Errors
export { RecorderError, isRecorderError, toRecorderError } from "./errors";
export type { RecorderErrorCode } from "./errors";

// Types
export type {
  RecorderRunState,
  RecorderStatus,
  RecordingMeta,
  RecordingResult,
  ScreenSource,
  StartOptions,
} from "./types";

/**
 * A minimal imperative handle: **`start()` then `stop()` resolves a `File`.**
 * Wraps {@link ScreenRecorder} for callers that only want the upload-ready file
 * and none of the metadata. Single-use per instance.
 */
export interface RecorderHandle {
  start(options?: StartOptions): Promise<void>;
  pause(): void;
  resume(): void;
  /** Finalise and resolve the recorded, upload-ready `File`. */
  stop(): Promise<File>;
  /** Abort without producing a file. */
  cancel(): void;
  /** True while actively capturing. */
  readonly isRecording: boolean;
}

/** Create a {@link RecorderHandle} whose `stop()` resolves directly to a `File`. */
export function createScreenRecorder(): RecorderHandle {
  const engine = new ScreenRecorder();
  return {
    start: (options?: StartOptions) => engine.start(options),
    pause: () => engine.pause(),
    resume: () => engine.resume(),
    stop: async () => (await engine.stop()).file,
    cancel: () => engine.cancel(),
    get isRecording() {
      return engine.isRecording;
    },
  };
}
