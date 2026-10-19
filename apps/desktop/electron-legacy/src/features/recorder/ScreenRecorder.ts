/**
 * `ScreenRecorder` — the imperative core of the recorder feature.
 *
 * Lifecycle: `start()` acquires a capture stream (in-app picker source or the
 * system `getDisplayMedia` picker) and begins a `MediaRecorder`; `pause()` /
 * `resume()` bracket the wall clock so paused time is excluded; `stop()` flushes
 * the buffered chunks into an upload-ready `File`. Instances are single-use —
 * create a fresh one per recording.
 *
 * The public contract in one line: **`start()` → `stop(): Promise<RecordingResult>`**,
 * where `result.file` is a named `File` you can hand straight to the uploader.
 */

import { acquireStream } from "./captureSources";
import { RecorderError, toRecorderError } from "./errors";
import { pickSupportedMimeType } from "./mediaSupport";
import type { MimeChoice } from "./mediaSupport";
import type { RecorderRunState, RecordingResult, StartOptions } from "./types";

/** How often (ms) `MediaRecorder` flushes a chunk, giving a live size readout. */
const CHUNK_INTERVAL_MS = 1000;

export class ScreenRecorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private readonly chunks: Blob[] = [];
  private mime: MimeChoice = { mimeType: "video/webm", extension: "webm" };

  private bytes = 0;
  /** Wall-clock ms accumulated across completed run segments (before pauses). */
  private accumulatedMs = 0;
  /** `performance.now()` timestamp of the current running segment's start. */
  private segmentStart = 0;
  private used = false;

  /** Low-level state, mirroring `MediaRecorder.state`. */
  get runState(): RecorderRunState {
    return (this.recorder?.state as RecorderRunState | undefined) ?? "inactive";
  }

  /** True while actively capturing (not paused, not stopped). */
  get isRecording(): boolean {
    return this.runState === "recording";
  }

  /** The live capture stream, for binding to a `<video>` preview element. */
  get previewStream(): MediaStream | null {
    return this.stream;
  }

  /** Negotiated container MIME type. */
  get mimeType(): string {
    return this.mime.mimeType;
  }

  /** Bytes buffered so far (updates roughly every {@link CHUNK_INTERVAL_MS}). */
  get sizeBytes(): number {
    return this.bytes;
  }

  /** Elapsed recorded time in ms, excluding any paused spans. */
  get elapsedMs(): number {
    if (this.runState === "recording") {
      return this.accumulatedMs + (performance.now() - this.segmentStart);
    }
    return this.accumulatedMs;
  }

  /**
   * Acquire the stream and begin recording. Rejects with a {@link RecorderError}
   * if permission is denied, the picker is cancelled, or capture is unsupported.
   */
  async start(options: StartOptions = {}): Promise<void> {
    if (this.used) {
      throw new RecorderError(
        "unknown",
        "This recorder instance has already been used. Create a new one.",
      );
    }
    this.used = true;

    let stream: MediaStream;
    try {
      stream = await acquireStream(options);
    } catch (err) {
      this.used = false; // allow a retry with a fresh call on the same instance
      throw toRecorderError(err);
    }

    this.stream = stream;
    this.mime = pickSupportedMimeType(options.preferredMimeTypes);

    // If the OS ends the capture (user hits the system "Stop sharing" control),
    // notify the caller so it can finalise.
    const [videoTrack] = stream.getVideoTracks();
    if (videoTrack && options.onStreamEnded) {
      videoTrack.addEventListener("ended", options.onStreamEnded, {
        once: true,
      });
    }

    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream, { mimeType: this.mime.mimeType });
    } catch (err) {
      this.releaseStream();
      throw toRecorderError(err);
    }

    recorder.ondataavailable = (event: BlobEvent) => {
      if (event.data && event.data.size > 0) {
        this.chunks.push(event.data);
        this.bytes += event.data.size;
      }
    };

    recorder.start(CHUNK_INTERVAL_MS);
    this.recorder = recorder;
    this.segmentStart = performance.now();
    this.accumulatedMs = 0;
  }

  /** Pause capture, freezing the elapsed clock. No-op unless actively recording. */
  pause(): void {
    const recorder = this.recorder;
    if (!recorder || recorder.state !== "recording") return;
    this.accumulatedMs += performance.now() - this.segmentStart;
    recorder.pause();
  }

  /** Resume a paused capture. No-op unless currently paused. */
  resume(): void {
    const recorder = this.recorder;
    if (!recorder || recorder.state !== "paused") return;
    this.segmentStart = performance.now();
    recorder.resume();
  }

  /**
   * Stop capturing, release the OS stream, and resolve the finished recording as
   * an upload-ready {@link RecordingResult}.
   */
  stop(): Promise<RecordingResult> {
    return new Promise<RecordingResult>((resolve, reject) => {
      const recorder = this.recorder;
      if (!recorder || recorder.state === "inactive") {
        reject(
          new RecorderError("unknown", "Recording has not been started."),
        );
        return;
      }

      // Close out the final running/paused segment before we tear down.
      if (recorder.state === "recording") {
        this.accumulatedMs += performance.now() - this.segmentStart;
      }
      const durationMs = Math.round(this.accumulatedMs);

      recorder.onstop = () => {
        this.releaseStream();
        const blob = new Blob(this.chunks, { type: this.mime.mimeType });
        const filename = `screen-${Date.now()}.${this.mime.extension}`;
        const file = new File([blob], filename, { type: this.mime.mimeType });
        resolve({
          file,
          blob,
          mimeType: this.mime.mimeType,
          sizeBytes: blob.size,
          durationMs,
          filename,
        });
      };

      recorder.onerror = () => {
        this.releaseStream();
        reject(new RecorderError("capture-failed", "Recording failed."));
      };

      // Flush any buffered data, then stop (paused recorders must be resumed to
      // emit their final chunk on some Chromium builds).
      try {
        if (recorder.state === "paused") recorder.resume();
        recorder.requestData();
      } catch {
        // requestData can throw if already stopping; safe to ignore.
      }
      recorder.stop();
    });
  }

  /** Abort without producing a result (e.g. on unmount). Idempotent. */
  cancel(): void {
    const recorder = this.recorder;
    if (recorder && recorder.state !== "inactive") {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      recorder.onerror = null;
      try {
        recorder.stop();
      } catch {
        // Ignore — we are tearing down regardless.
      }
    }
    this.recorder = null;
    this.releaseStream();
  }

  private releaseStream(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }
}
