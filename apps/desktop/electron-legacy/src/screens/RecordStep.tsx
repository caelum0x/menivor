import { useCallback, useEffect, useRef, useState } from "react";

import { ScreenRecorder, listScreenSources } from "../lib/recorder";
import type { ScreenSource } from "../lib/recorder";

interface RecordStepProps {
  /** Called with the finished WebM blob once the user stops recording. */
  onRecorded: (blob: Blob) => void;
}

type Phase = "idle" | "picking" | "recording";

/**
 * Record step: pick a screen/window via the preload `getScreenSources` bridge,
 * capture it with {@link ScreenRecorder}, and hand the finished blob up to the
 * Create screen. Review + configuration happen in the next step, so this stays
 * focused on capture. The recorder is cancelled on unmount so no OS stream leaks.
 */
export function RecordStep({ onRecorded }: RecordStepProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [sources, setSources] = useState<ScreenSource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  const recorderRef = useRef<ScreenRecorder | null>(null);
  const timerRef = useRef<number | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      clearTimer();
      recorderRef.current?.cancel();
    };
  }, [clearTimer]);

  const openPicker = useCallback(async () => {
    setError(null);
    setPhase("picking");
    try {
      setSources(await listScreenSources());
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not list screen sources.",
      );
      setPhase("idle");
    }
  }, []);

  const startRecording = useCallback(async (sourceId: string) => {
    setError(null);
    const recorder = new ScreenRecorder();
    try {
      await recorder.start(sourceId);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not start recording.",
      );
      return;
    }
    recorderRef.current = recorder;
    setElapsed(0);
    setPhase("recording");
    timerRef.current = window.setInterval(
      () => setElapsed((s) => s + 1),
      1000,
    );
  }, []);

  const stopRecording = useCallback(async () => {
    clearTimer();
    const recorder = recorderRef.current;
    if (!recorder) return;
    try {
      const blob = await recorder.stop();
      onRecorded(blob);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Recording failed.");
      setPhase("idle");
    } finally {
      recorderRef.current = null;
    }
  }, [clearTimer, onRecorded]);

  return (
    <section className="view">
      <div className="view-head">
        <h1 className="view-title">Create a reel</h1>
        <p className="view-sub">
          Record a demo of your product, then turn it into a UGC reel.
        </p>
      </div>

      {error && <p className="error-text">{error}</p>}

      {(phase === "idle" || phase === "picking") && (
        <div className="card panel">
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => void openPicker()}
          >
            Choose a screen or window
          </button>

          {phase === "picking" && (
            <div className="source-grid">
              {sources.length === 0 && (
                <p className="muted">No capturable sources found.</p>
              )}
              {sources.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className="source-tile"
                  onClick={() => void startRecording(s.id)}
                >
                  <img className="source-thumb" src={s.thumbnailDataUrl} alt="" />
                  <span className="source-name" title={s.name}>
                    {s.name}
                  </span>
                  <span className="source-kind">{s.kind}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {phase === "recording" && (
        <div className="card panel recording-panel">
          <div className="rec-indicator">
            <span className="rec-dot" aria-hidden />
            Recording — {formatDuration(elapsed)}
          </div>
          <button
            type="button"
            className="btn btn--danger"
            onClick={() => void stopRecording()}
          >
            Stop recording
          </button>
        </div>
      )}
    </section>
  );
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0");
  const s = (seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}
