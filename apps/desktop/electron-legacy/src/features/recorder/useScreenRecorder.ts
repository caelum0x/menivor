/**
 * `useScreenRecorder` — a React binding over {@link ScreenRecorder}.
 *
 * It owns a single engine instance per recording, translates the imperative
 * lifecycle into declarative React state (status, live clock, live size, preview
 * stream, final result), maps failures onto typed {@link RecorderError}s, and
 * cleans everything up on unmount. Components render from `status`; they never
 * touch the engine directly.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ScreenRecorder } from "./ScreenRecorder";
import { listScreenSources } from "./captureSources";
import { RecorderError, toRecorderError } from "./errors";
import { isRecordingSupported } from "./mediaSupport";
import type {
  RecorderStatus,
  RecordingResult,
  ScreenSource,
  StartOptions,
} from "./types";

/** How often the live clock + size readout are refreshed while recording (ms). */
const READOUT_INTERVAL_MS = 250;

export interface UseScreenRecorder {
  /** High-level status driving which panel phase renders. */
  readonly status: RecorderStatus;
  /** Enumerated capture sources for the in-app picker (empty until loaded). */
  readonly sources: ScreenSource[];
  /** True while the source list is being fetched. */
  readonly sourcesLoading: boolean;
  /** Most recent error, if any. */
  readonly error: RecorderError | null;
  /** Live recorded duration in ms (frozen while paused / after stop). */
  readonly elapsedMs: number;
  /** Live recorded size in bytes. */
  readonly sizeBytes: number;
  /** Live capture stream for the `<video>` preview (null when not capturing). */
  readonly previewStream: MediaStream | null;
  /** The finished recording once available. */
  readonly result: RecordingResult | null;
  /** Whether this environment supports screen recording at all. */
  readonly isSupported: boolean;

  /** Fetch the list of capturable screens/windows. */
  loadSources(): Promise<void>;
  /** Begin a recording (with an in-app `sourceId`, or via the system picker). */
  start(options?: StartOptions): Promise<void>;
  /** Pause the active recording. */
  pause(): void;
  /** Resume a paused recording. */
  resume(): void;
  /** Finalise and resolve the recording (also updates `result`/`status`). */
  stop(): Promise<RecordingResult | null>;
  /** Discard the current recording/result and return to idle. */
  discard(): void;
}

export function useScreenRecorder(): UseScreenRecorder {
  const engineRef = useRef<ScreenRecorder | null>(null);
  const tickRef = useRef<number | null>(null);

  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [sources, setSources] = useState<ScreenSource[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [error, setError] = useState<RecorderError | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [sizeBytes, setSizeBytes] = useState(0);
  const [previewStream, setPreviewStream] = useState<MediaStream | null>(null);
  const [result, setResult] = useState<RecordingResult | null>(null);

  const isSupported = useMemo(() => isRecordingSupported(), []);

  const stopTick = useCallback(() => {
    if (tickRef.current !== null) {
      window.clearInterval(tickRef.current);
      tickRef.current = null;
    }
  }, []);

  const startTick = useCallback(() => {
    stopTick();
    tickRef.current = window.setInterval(() => {
      const engine = engineRef.current;
      if (!engine) return;
      setElapsedMs(engine.elapsedMs);
      setSizeBytes(engine.sizeBytes);
    }, READOUT_INTERVAL_MS);
  }, [stopTick]);

  const stop = useCallback(async (): Promise<RecordingResult | null> => {
    const engine = engineRef.current;
    if (!engine) return null;
    stopTick();
    setStatus("stopping");
    try {
      const res = await engine.stop();
      setElapsedMs(res.durationMs);
      setSizeBytes(res.sizeBytes);
      setPreviewStream(null);
      setResult(res);
      setStatus("review");
      return res;
    } catch (err) {
      setError(toRecorderError(err));
      setPreviewStream(null);
      setStatus("error");
      return null;
    } finally {
      engineRef.current = null;
    }
  }, [stopTick]);

  // Keep a stable reference to the latest `stop` for the out-of-band
  // "OS stopped sharing" callback, which is registered at `start()` time.
  const stopRef = useRef(stop);
  useEffect(() => {
    stopRef.current = stop;
  }, [stop]);

  // Tear down on unmount: cancel any live capture and clear the timer.
  useEffect(() => {
    return () => {
      stopTick();
      engineRef.current?.cancel();
      engineRef.current = null;
    };
  }, [stopTick]);

  const loadSources = useCallback(async () => {
    setError(null);
    setSourcesLoading(true);
    try {
      setSources(await listScreenSources());
    } catch (err) {
      setError(toRecorderError(err));
      setStatus("error");
    } finally {
      setSourcesLoading(false);
    }
  }, []);

  const start = useCallback(
    async (options: StartOptions = {}) => {
      if (!isSupported) {
        setError(
          new RecorderError(
            "not-supported",
            "Screen recording is not supported in this environment.",
          ),
        );
        setStatus("error");
        return;
      }

      setError(null);
      setResult(null);
      setElapsedMs(0);
      setSizeBytes(0);
      setStatus("acquiring");

      const engine = new ScreenRecorder();
      try {
        await engine.start({
          ...options,
          onStreamEnded: () => {
            void stopRef.current();
          },
        });
      } catch (err) {
        const recorderError = toRecorderError(err);
        // A cancelled picker is a normal action, not an error state.
        setStatus(recorderError.code === "cancelled" ? "idle" : "error");
        if (recorderError.code !== "cancelled") setError(recorderError);
        return;
      }

      engineRef.current = engine;
      setPreviewStream(engine.previewStream);
      setStatus("recording");
      startTick();
    },
    [isSupported, startTick],
  );

  const pause = useCallback(() => {
    const engine = engineRef.current;
    if (!engine || !engine.isRecording) return;
    engine.pause();
    setElapsedMs(engine.elapsedMs);
    setSizeBytes(engine.sizeBytes);
    stopTick();
    setStatus("paused");
  }, [stopTick]);

  const resume = useCallback(() => {
    const engine = engineRef.current;
    if (!engine || engine.runState !== "paused") return;
    engine.resume();
    setStatus("recording");
    startTick();
  }, [startTick]);

  const discard = useCallback(() => {
    engineRef.current?.cancel();
    engineRef.current = null;
    stopTick();
    setResult(null);
    setPreviewStream(null);
    setElapsedMs(0);
    setSizeBytes(0);
    setError(null);
    setStatus("idle");
  }, [stopTick]);

  return {
    status,
    sources,
    sourcesLoading,
    error,
    elapsedMs,
    sizeBytes,
    previewStream,
    result,
    isSupported,
    loadSources,
    start,
    pause,
    resume,
    stop,
    discard,
  };
}
