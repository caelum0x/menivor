import { useCallback, useEffect, useRef, useState } from "react";

import { formatBytes, formatDuration } from "./format";
import { useScreenRecorder } from "./useScreenRecorder";
import type { RecordingMeta, ScreenSource } from "./types";
import "./RecorderPanel.css";

export interface RecorderPanelProps {
  /**
   * Called when the user accepts a finished recording. `file` is upload-ready
   * (a named `File`); `meta` carries duration/size/MIME for display or the job.
   */
  onComplete?: (file: File, meta: RecordingMeta) => void;
  /** Attempt to capture audio alongside video (default `false`). */
  audio?: boolean;
  /** Target frame rate hint for the capture (default `30`). */
  frameRate?: number;
}

/**
 * RecorderPanel — self-contained screen-recording UI.
 *
 * Flow: pick a source (in-app grid or the system picker) → live capture with a
 * duration + size readout and pause/resume/stop → review the clip → accept it,
 * which hands the upload-ready `File` back to the parent via `onComplete`.
 */
export function RecorderPanel({
  onComplete,
  audio = false,
  frameRate = 30,
}: RecorderPanelProps) {
  const recorder = useScreenRecorder();
  const {
    status,
    sources,
    sourcesLoading,
    error,
    elapsedMs,
    sizeBytes,
    previewStream,
    result,
    isSupported,
  } = recorder;

  const [pickerOpen, setPickerOpen] = useState(false);
  const [reviewUrl, setReviewUrl] = useState<string | null>(null);

  const liveVideoRef = useRef<HTMLVideoElement | null>(null);

  // Bind the live capture stream to the preview element.
  useEffect(() => {
    const el = liveVideoRef.current;
    if (!el) return;
    el.srcObject = previewStream;
    if (previewStream) el.play().catch(() => undefined);
  }, [previewStream]);

  // Manage the object URL for the recorded-clip review, revoking on change.
  useEffect(() => {
    if (!result) {
      setReviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(result.file);
    setReviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [result]);

  const openPicker = useCallback(async () => {
    setPickerOpen(true);
    await recorder.loadSources();
  }, [recorder]);

  const startFromSource = useCallback(
    (source: ScreenSource) => {
      setPickerOpen(false);
      void recorder.start({ sourceId: source.id, audio, frameRate });
    },
    [recorder, audio, frameRate],
  );

  const startFromSystemPicker = useCallback(() => {
    setPickerOpen(false);
    void recorder.start({ audio, frameRate });
  }, [recorder, audio, frameRate]);

  const accept = useCallback(() => {
    if (!result) return;
    onComplete?.(result.file, {
      durationMs: result.durationMs,
      sizeBytes: result.sizeBytes,
      mimeType: result.mimeType,
    });
  }, [result, onComplete]);

  const discard = useCallback(() => {
    setPickerOpen(false);
    recorder.discard();
  }, [recorder]);

  if (!isSupported) {
    return (
      <div className="card panel recorder">
        <p className="error-text">
          Screen recording is not available in this environment.
        </p>
        <p className="muted">
          This panel needs a Chromium runtime with the getDisplayMedia and
          MediaRecorder APIs.
        </p>
      </div>
    );
  }

  const isLive = status === "recording" || status === "paused";

  return (
    <div className="recorder">
      {error && <p className="error-text">{error.message}</p>}

      {/* Idle: choose a source ------------------------------------------------ */}
      {(status === "idle" || status === "error") && (
        <div className="card panel recorder__intro">
          <div className="recorder__actions">
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => void openPicker()}
              disabled={sourcesLoading}
            >
              {sourcesLoading ? "Finding sources…" : "Choose a screen or window"}
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={startFromSystemPicker}
            >
              Use system picker
            </button>
          </div>

          {pickerOpen && !sourcesLoading && (
            <>
              <div className="recorder__divider">Capturable sources</div>
              {sources.length === 0 ? (
                <p className="muted">
                  No capturable screens or windows were found.
                </p>
              ) : (
                <div className="source-grid">
                  {sources.map((source) => (
                    <button
                      key={source.id}
                      type="button"
                      className="source-tile"
                      onClick={() => startFromSource(source)}
                    >
                      <img
                        className="source-thumb"
                        src={source.thumbnailDataUrl}
                        alt=""
                      />
                      <span className="source-name" title={source.name}>
                        {source.name}
                      </span>
                      <span className="source-kind">{source.kind}</span>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Acquiring ----------------------------------------------------------- */}
      {status === "acquiring" && (
        <div className="card panel">
          <div className="recorder__status">
            <span className="recorder__spinner" aria-hidden />
            Preparing capture… approve the screen-share prompt if shown.
          </div>
        </div>
      )}

      {/* Live capture -------------------------------------------------------- */}
      {isLive && (
        <div className="card panel">
          <video
            ref={liveVideoRef}
            className="recorder__preview"
            muted
            autoPlay
            playsInline
          />

          <div className="recorder__bar">
            <div className="recorder__stats">
              <div className="rec-indicator">
                <span
                  className={
                    status === "paused"
                      ? "rec-dot recorder__paused-dot"
                      : "rec-dot"
                  }
                  aria-hidden
                />
                {status === "paused" ? "Paused" : "Recording"}
              </div>
              <div className="recorder__stat">
                <span className="recorder__stat-label">Duration</span>
                <span className="recorder__stat-value">
                  {formatDuration(elapsedMs)}
                </span>
              </div>
              <div className="recorder__stat">
                <span className="recorder__stat-label">Size</span>
                <span className="recorder__stat-value">
                  {formatBytes(sizeBytes)}
                </span>
              </div>
            </div>

            <div className="recorder__controls">
              {status === "recording" ? (
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={recorder.pause}
                >
                  Pause
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={recorder.resume}
                >
                  Resume
                </button>
              )}
              <button
                type="button"
                className="btn btn--danger"
                onClick={() => void recorder.stop()}
              >
                Stop recording
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Finalising ---------------------------------------------------------- */}
      {status === "stopping" && (
        <div className="card panel">
          <div className="recorder__status">
            <span className="recorder__spinner" aria-hidden />
            Finalising recording…
          </div>
        </div>
      )}

      {/* Review -------------------------------------------------------------- */}
      {status === "review" && result && reviewUrl && (
        <div className="card panel">
          <video className="recorder__preview" src={reviewUrl} controls />

          <div className="recorder__bar">
            <div className="recorder__stats">
              <div className="recorder__stat">
                <span className="recorder__stat-label">Duration</span>
                <span className="recorder__stat-value">
                  {formatDuration(result.durationMs)}
                </span>
              </div>
              <div className="recorder__stat">
                <span className="recorder__stat-label">Size</span>
                <span className="recorder__stat-value">
                  {formatBytes(result.sizeBytes)}
                </span>
              </div>
            </div>

            <div className="recorder__controls">
              <button type="button" className="btn btn--ghost" onClick={discard}>
                Discard
              </button>
              <button
                type="button"
                className="btn btn--primary"
                onClick={accept}
              >
                Use this recording
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
