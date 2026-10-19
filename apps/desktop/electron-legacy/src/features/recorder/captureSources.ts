/**
 * Stream acquisition for the recorder.
 *
 * Two supported paths, both feeding `MediaRecorder`:
 *  1. **In-app picker** — the renderer enumerates `desktopCapturer` sources via
 *     the preload bridge (`getScreenSources`), the user taps one, and we open
 *     that exact source with Chromium's `chromeMediaSource: "desktop"`
 *     constraint (Electron's supported route for a pre-chosen source).
 *  2. **System picker** — no source id is supplied, so we call the
 *     browser-standard `navigator.mediaDevices.getDisplayMedia`, which surfaces
 *     the OS/native screen-share picker.
 *
 * Either way the caller receives a live `MediaStream` ready for preview + record.
 */

import type { ScreenSource, StartOptions } from "./types";
import { RecorderError } from "./errors";

const DEFAULT_FRAME_RATE = 30;
const DEFAULT_MAX_WIDTH = 1920;
const DEFAULT_MAX_HEIGHT = 1080;

/**
 * Non-standard Chromium desktop-capture constraint shape used by Electron. It is
 * not expressible with the standard `MediaStreamConstraints` type, so we model it
 * explicitly and cast at the call site.
 */
interface DesktopCaptureConstraints {
  audio: false;
  video: {
    mandatory: {
      chromeMediaSource: "desktop";
      chromeMediaSourceId: string;
      maxWidth: number;
      maxHeight: number;
      maxFrameRate: number;
    };
  };
}

/** Enumerate capturable screens/windows for the in-app picker (via main). */
export function listScreenSources(): Promise<ScreenSource[]> {
  if (typeof window === "undefined" || !window.reelforge) {
    return Promise.reject(
      new RecorderError(
        "not-supported",
        "The recorder bridge is unavailable in this environment.",
      ),
    );
  }
  return window.reelforge.getScreenSources();
}

/** Acquire a live capture stream for the given options (picker vs. system). */
export async function acquireStream(
  options: StartOptions,
): Promise<MediaStream> {
  if (typeof options.sourceId === "string" && options.sourceId.length > 0) {
    return acquireFromSourceId(options.sourceId, options);
  }
  return acquireViaDisplayMedia(options);
}

/** Open a pre-chosen Electron source id through the desktop constraint. */
async function acquireFromSourceId(
  sourceId: string,
  options: StartOptions,
): Promise<MediaStream> {
  const constraints: DesktopCaptureConstraints = {
    audio: false,
    video: {
      mandatory: {
        chromeMediaSource: "desktop",
        chromeMediaSourceId: sourceId,
        maxWidth: options.maxWidth ?? DEFAULT_MAX_WIDTH,
        maxHeight: options.maxHeight ?? DEFAULT_MAX_HEIGHT,
        maxFrameRate: options.frameRate ?? DEFAULT_FRAME_RATE,
      },
    },
  };

  // The desktop constraint is a Chromium/Electron extension, so cast through
  // `unknown` to satisfy the standard DOM typings.
  return navigator.mediaDevices.getUserMedia(
    constraints as unknown as MediaStreamConstraints,
  );
}

/** Open the browser-standard screen picker via `getDisplayMedia`. */
async function acquireViaDisplayMedia(
  options: StartOptions,
): Promise<MediaStream> {
  const video: MediaTrackConstraints = {
    frameRate: { ideal: options.frameRate ?? DEFAULT_FRAME_RATE },
    width: { max: options.maxWidth ?? DEFAULT_MAX_WIDTH },
    height: { max: options.maxHeight ?? DEFAULT_MAX_HEIGHT },
  };

  return navigator.mediaDevices.getDisplayMedia({
    video,
    audio: options.audio ?? false,
  });
}
