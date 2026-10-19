/**
 * Screen recording via Electron's desktop capturer.
 *
 * The renderer asks main for the list of capturable sources (through the preload
 * bridge), then opens a media stream for the chosen source with the Chromium
 * `desktop` constraint and records it to a WebM blob with `MediaRecorder`. The
 * resulting blob is uploaded through the presign flow and its R2 key becomes the
 * job's `screen_recording_key`.
 */

import type { ScreenSource } from "../../electron/ipc";

export type { ScreenSource };

/** Non-standard Chromium desktop-capture constraint shape used by Electron. */
interface DesktopCaptureConstraints {
  audio: false;
  video: {
    mandatory: {
      chromeMediaSource: "desktop";
      chromeMediaSourceId: string;
      maxWidth?: number;
      maxHeight?: number;
      maxFrameRate?: number;
    };
  };
}

/** Enumerate capturable screens/windows for the picker (delegates to main). */
export function listScreenSources(): Promise<ScreenSource[]> {
  return window.reelforge.getScreenSources();
}

/** Pick a supported WebM MIME type the current runtime can actually record. */
function pickMimeType(): string {
  const candidates = [
    "video/webm;codecs=vp9",
    "video/webm;codecs=vp8",
    "video/webm",
  ];
  for (const type of candidates) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return "video/webm";
}

/**
 * A minimal, self-contained screen recorder. `start` opens the stream for a
 * source id and begins capturing; `stop` finalises and resolves the recorded
 * `Blob`. The instance is single-use — create a new one per recording.
 */
export class ScreenRecorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  readonly mimeType: string = pickMimeType();

  /** True while a recording is actively capturing. */
  get isRecording(): boolean {
    return this.recorder?.state === "recording";
  }

  async start(sourceId: string): Promise<void> {
    if (this.recorder) throw new Error("This recorder has already been used.");

    const constraints: DesktopCaptureConstraints = {
      audio: false,
      video: {
        mandatory: {
          chromeMediaSource: "desktop",
          chromeMediaSourceId: sourceId,
          maxWidth: 1920,
          maxHeight: 1080,
          maxFrameRate: 30,
        },
      },
    };

    // The desktop constraint is non-standard, so cast through `unknown`.
    this.stream = await navigator.mediaDevices.getUserMedia(
      constraints as unknown as MediaStreamConstraints,
    );

    const recorder = new MediaRecorder(this.stream, { mimeType: this.mimeType });
    recorder.ondataavailable = (event: BlobEvent) => {
      if (event.data.size > 0) this.chunks.push(event.data);
    };
    recorder.start(1000);
    this.recorder = recorder;
  }

  /** Stop capturing, release the OS stream, and resolve the recorded blob. */
  stop(): Promise<Blob> {
    return new Promise((resolve, reject) => {
      const recorder = this.recorder;
      if (!recorder) {
        reject(new Error("Recording has not been started."));
        return;
      }
      recorder.onstop = () => {
        this.releaseStream();
        resolve(new Blob(this.chunks, { type: this.mimeType }));
      };
      recorder.onerror = () => {
        this.releaseStream();
        reject(new Error("Recording failed."));
      };
      recorder.stop();
    });
  }

  /** Abort a recording without producing a blob (e.g. on unmount). */
  cancel(): void {
    if (this.recorder && this.recorder.state !== "inactive") {
      this.recorder.onstop = null;
      this.recorder.stop();
    }
    this.releaseStream();
  }

  private releaseStream(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }
}
