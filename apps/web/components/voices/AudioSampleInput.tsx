"use client";

import * as React from "react";
import { AlertCircle, Mic, Square, Trash2, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  MAX_SAMPLE_BYTES,
  MAX_SAMPLE_SECONDS,
  MIN_SAMPLE_SECONDS,
} from "@/components/voices/voice-utils";

/** A captured voice sample plus a local object URL for preview. */
export interface AudioSample {
  file: File;
  /** `URL.createObjectURL` handle for the `<audio>` preview. */
  url: string;
  source: "recorded" | "uploaded";
  durationLabel?: string;
}

interface AudioSampleInputProps {
  value: AudioSample | null;
  onChange: (sample: AudioSample | null) => void;
  disabled?: boolean;
}

/** Map a MediaRecorder mime type to a file extension for the sample name. */
function extForMime(mime: string): string {
  const m = mime.toLowerCase();
  if (m.includes("webm")) return "webm";
  if (m.includes("ogg")) return "ogg";
  if (m.includes("mp4") || m.includes("m4a") || m.includes("aac")) return "m4a";
  if (m.includes("wav")) return "wav";
  if (m.includes("mpeg") || m.includes("mp3")) return "mp3";
  return "webm";
}

/** Pick a supported audio mime type for MediaRecorder, or "" for the default. */
function preferredMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "";
  const candidates = ["audio/webm", "audio/mp4", "audio/ogg"];
  for (const c of candidates) {
    if (MediaRecorder.isTypeSupported(c)) return c;
  }
  return "";
}

function formatSeconds(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let size = bytes / 1024;
  let i = 0;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i += 1;
  }
  return `${size.toFixed(1)} ${units[i]}`;
}

/**
 * Lets the creator provide a voice sample either by recording live audio
 * (MediaRecorder) or by uploading an audio file. Reports the resulting `File`
 * up via `onChange`; the parent handles presign + upload + clone. Object URLs
 * are revoked on replacement/unmount to avoid leaks.
 */
export function AudioSampleInput({
  value,
  onChange,
  disabled = false,
}: AudioSampleInputProps) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const recorderRef = React.useRef<MediaRecorder | null>(null);
  const chunksRef = React.useRef<Blob[]>([]);
  const timerRef = React.useRef<ReturnType<typeof setInterval> | null>(null);
  // Track the currently-published object URL so we can revoke the previous one.
  const urlRef = React.useRef<string | null>(null);
  // Mirror `elapsed` so the recorder's onstop closure sees the final value
  // without recreating the callback on every tick.
  const elapsedRef = React.useRef(0);

  const [isRecording, setIsRecording] = React.useState(false);
  const [elapsed, setElapsed] = React.useState(0);
  const [error, setError] = React.useState<string | null>(null);

  const canRecord =
    typeof navigator !== "undefined" &&
    typeof navigator.mediaDevices?.getUserMedia === "function" &&
    typeof MediaRecorder !== "undefined";

  const publish = React.useCallback(
    (next: AudioSample | null) => {
      if (urlRef.current && urlRef.current !== next?.url) {
        URL.revokeObjectURL(urlRef.current);
      }
      urlRef.current = next?.url ?? null;
      onChange(next);
    },
    [onChange],
  );

  const stopTimer = React.useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Clean up any live recorder, timer, and object URL on unmount.
  React.useEffect(() => {
    return () => {
      stopTimer();
      recorderRef.current?.stream.getTracks().forEach((t) => t.stop());
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, [stopTimer]);

  const startRecording = React.useCallback(async () => {
    setError(null);
    if (!canRecord) {
      setError("Recording is not supported in this browser — upload a file instead.");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Microphone access was blocked. Allow it, or upload a file instead.");
      return;
    }

    const mimeType = preferredMimeType();
    const recorder = mimeType
      ? new MediaRecorder(stream, { mimeType })
      : new MediaRecorder(stream);
    recorderRef.current = recorder;
    chunksRef.current = [];

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onstop = () => {
      stopTimer();
      stream.getTracks().forEach((t) => t.stop());
      const type = recorder.mimeType || mimeType || "audio/webm";
      const blob = new Blob(chunksRef.current, { type });
      chunksRef.current = [];
      const seconds = elapsedRef.current;
      if (blob.size <= 0) {
        setError("That recording was empty. Please try again.");
        return;
      }
      const file = new File(
        [blob],
        `brand-voice-${Date.now()}.${extForMime(type)}`,
        { type },
      );
      publish({
        file,
        url: URL.createObjectURL(blob),
        source: "recorded",
        durationLabel: formatSeconds(seconds),
      });
    };

    // Reset any previous sample before starting a new take.
    publish(null);
    setElapsed(0);
    elapsedRef.current = 0;
    recorder.start();
    setIsRecording(true);
    timerRef.current = setInterval(() => {
      setElapsed((prev) => {
        const next = prev + 1;
        elapsedRef.current = next;
        return next;
      });
    }, 1000);
  }, [canRecord, publish, stopTimer]);

  const stopRecording = React.useCallback(() => {
    setIsRecording(false);
    stopTimer();
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }, [stopTimer]);

  const onPickFile = React.useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (!file) return;
      setError(null);
      if (!file.type.startsWith("audio/")) {
        setError("Please choose an audio file (MP3, WAV, M4A, WebM…).");
        return;
      }
      if (file.size <= 0) {
        setError("That file looks empty.");
        return;
      }
      if (file.size > MAX_SAMPLE_BYTES) {
        setError(`File is too large (max ${formatBytes(MAX_SAMPLE_BYTES)}).`);
        return;
      }
      publish({
        file,
        url: URL.createObjectURL(file),
        source: "uploaded",
      });
    },
    [publish],
  );

  const clear = React.useCallback(() => {
    setError(null);
    setElapsed(0);
    elapsedRef.current = 0;
    if (inputRef.current) inputRef.current.value = "";
    publish(null);
  }, [publish]);

  // ----- Captured sample: preview + replace -----
  if (value) {
    return (
      <div className="space-y-3 rounded-lg border border-border bg-secondary/20 p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-medium">
            {value.source === "recorded" ? "Recorded sample" : value.file.name}
            {value.durationLabel && (
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                {value.durationLabel}
              </span>
            )}
          </p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={clear}
            disabled={disabled}
          >
            <Trash2 /> Remove
          </Button>
        </div>
        {/* eslint-disable-next-line jsx-a11y/media-has-caption -- user audio, no captions */}
        <audio controls src={value.url} className="w-full" />
      </div>
    );
  }

  // ----- Empty: record or upload -----
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        {isRecording ? (
          <Button
            type="button"
            variant="destructive"
            onClick={stopRecording}
            disabled={disabled}
            className="w-full"
          >
            <Square /> Stop ({formatSeconds(elapsed)})
          </Button>
        ) : (
          <Button
            type="button"
            variant="outline"
            onClick={() => void startRecording()}
            disabled={disabled || !canRecord}
            className="w-full"
          >
            <Mic /> Record sample
          </Button>
        )}

        <Button
          type="button"
          variant="outline"
          onClick={() => inputRef.current?.click()}
          disabled={disabled || isRecording}
          className="w-full"
        >
          <UploadCloud /> Upload audio
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept="audio/*"
          className="sr-only"
          onChange={(e) => onPickFile(e.target.files)}
        />
      </div>

      <p
        className={cn(
          "text-xs",
          isRecording ? "text-destructive" : "text-muted-foreground",
        )}
      >
        {isRecording
          ? `Recording… speak naturally for ${MIN_SAMPLE_SECONDS}-${MAX_SAMPLE_SECONDS} seconds, then Stop.`
          : `Record or upload ${MIN_SAMPLE_SECONDS}-${MAX_SAMPLE_SECONDS} seconds of clear speech (max ${formatBytes(MAX_SAMPLE_BYTES)}).`}
      </p>

      {error && (
        <p
          role="alert"
          className="flex items-center gap-2 text-sm text-destructive"
        >
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          {error}
        </p>
      )}
    </div>
  );
}
