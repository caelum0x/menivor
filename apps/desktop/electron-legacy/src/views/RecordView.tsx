import { useCallback, useEffect, useRef, useState } from "react";

import { presignAndUpload } from "../lib/api";
import { ScreenRecorder, listScreenSources } from "../lib/recorder";
import type { ScreenSource } from "../lib/recorder";

interface RecordViewProps {
  onUploaded: (key: string) => void;
}

type Phase = "idle" | "picking" | "recording" | "review" | "uploading";

/**
 * Record view: pick a screen/window, capture it to a WebM blob, review the clip,
 * then upload it via the presign flow. On a successful upload the R2 key is handed
 * up to the shell, which advances to the Generate view.
 */
export function RecordView({ onUploaded }: RecordViewProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [sources, setSources] = useState<ScreenSource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [uploadPct, setUploadPct] = useState(0);

  const recorderRef = useRef<ScreenRecorder | null>(null);
  const blobRef = useRef<Blob | null>(null);
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
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [clearTimer, previewUrl]);

  const openPicker = useCallback(async () => {
    setError(null);
    setPhase("picking");
    try {
      setSources(await listScreenSources());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not list screen sources.");
      setPhase("idle");
    }
  }, []);

  const startRecording = useCallback(
    async (sourceId: string) => {
      setError(null);
      const recorder = new ScreenRecorder();
      try {
        await recorder.start(sourceId);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not start recording.");
        return;
      }
      recorderRef.current = recorder;
      setElapsed(0);
      setPhase("recording");
      timerRef.current = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    },
    [],
  );

  const stopRecording = useCallback(async () => {
    clearTimer();
    const recorder = recorderRef.current;
    if (!recorder) return;
    try {
      const blob = await recorder.stop();
      blobRef.current = blob;
      const url = URL.createObjectURL(blob);
      setPreviewUrl(url);
      setPhase("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Recording failed.");
      setPhase("idle");
    } finally {
      recorderRef.current = null;
    }
  }, [clearTimer]);

  const discard = useCallback(() => {
    blobRef.current = null;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    setPhase("idle");
  }, [previewUrl]);

  const upload = useCallback(async () => {
    const blob = blobRef.current;
    if (!blob) return;
    setPhase("uploading");
    setUploadPct(0);
    setError(null);
    try {
      const filename = `screen-${Date.now()}.webm`;
      const { key } = await presignAndUpload(blob, filename, (f) =>
        setUploadPct(Math.round(f * 100)),
      );
      onUploaded(key);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
      setPhase("review");
    }
  }, [onUploaded]);

  return (
    <section className="view">
      <div className="view-head">
        <h1 className="view-title">Record your screen</h1>
        <p className="view-sub">
          Capture a demo of your product, then turn it into a UGC reel.
        </p>
      </div>

      {error && <p className="error-text">{error}</p>}

      {(phase === "idle" || phase === "picking") && (
        <div className="card panel">
          <button type="button" className="btn btn--primary" onClick={openPicker}>
            Choose a screen or window
          </button>

          {phase === "picking" && (
            <div className="source-grid">
              {sources.length === 0 && <p className="muted">No capturable sources found.</p>}
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
          <button type="button" className="btn btn--danger" onClick={() => void stopRecording()}>
            Stop recording
          </button>
        </div>
      )}

      {(phase === "review" || phase === "uploading") && previewUrl && (
        <div className="card panel">
          <video className="preview" src={previewUrl} controls />
          {phase === "uploading" ? (
            <div className="progress">
              <div className="progress-bar" style={{ width: `${uploadPct}%` }} />
              <span className="progress-label">Uploading… {uploadPct}%</span>
            </div>
          ) : (
            <div className="panel-actions">
              <button type="button" className="btn btn--ghost" onClick={discard}>
                Discard
              </button>
              <button type="button" className="btn btn--primary" onClick={() => void upload()}>
                Use this recording
              </button>
            </div>
          )}
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
