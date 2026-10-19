"use client";

// Quick-create presentation component: narration audio upload (BYOV).

import * as React from "react";
import {
  AlertCircle,
  CheckCircle2,
  FileAudio,
  Loader2,
  UploadCloud,
  X,
} from "lucide-react";
import { ApiError, presignAndUpload } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface UploadedVoiceover {
  key: string;
  name: string;
  sizeLabel: string;
}

interface VoiceoverDropzoneProps {
  value: UploadedVoiceover | null;
  onUploaded: (voiceover: UploadedVoiceover) => void;
  onClear: () => void;
}

type Status = "idle" | "uploading" | "done" | "error";

/** The API's upload allowlist admits `audio/wav` + `audio/mpeg` only. */
const ACCEPTED_AUDIO = new Set(["audio/wav", "audio/x-wav", "audio/mpeg"]);
const ACCEPT_ATTR = ".wav,.mp3,audio/wav,audio/mpeg";
const MAX_AUDIO_BYTES = 100 * 1024 * 1024;

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

function normalizedType(file: File): string {
  const type = (file.type || "").toLowerCase();
  if (ACCEPTED_AUDIO.has(type)) {
    return type === "audio/x-wav" ? "audio/wav" : type;
  }
  // Some browsers report an empty MIME for .wav/.mp3 — infer from extension.
  const name = file.name.toLowerCase();
  if (name.endsWith(".wav")) return "audio/wav";
  if (name.endsWith(".mp3")) return "audio/mpeg";
  return "";
}

function validate(file: File): string | null {
  if (!normalizedType(file)) {
    return "Please choose a WAV or MP3 narration file.";
  }
  if (file.size <= 0) return "That file looks empty.";
  if (file.size > MAX_AUDIO_BYTES) {
    return `File is too large (max ${formatBytes(MAX_AUDIO_BYTES)}).`;
  }
  return null;
}

/**
 * Upload the creator's own narration audio (presign -> PUT -> register) and
 * hand back its R2 key for `voiceover_key`. The narration's transcript drives
 * the karaoke captions and its duration sizes the whole reel.
 */
export function VoiceoverDropzone({
  value,
  onUploaded,
  onClear,
}: VoiceoverDropzoneProps) {
  const [status, setStatus] = React.useState<Status>(value ? "done" : "idle");
  const [error, setError] = React.useState("");
  const [dragOver, setDragOver] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement | null>(null);

  const upload = React.useCallback(
    async (file: File) => {
      const problem = validate(file);
      if (problem) {
        setStatus("error");
        setError(problem);
        return;
      }
      setStatus("uploading");
      setError("");
      try {
        const mime = normalizedType(file);
        const named =
          file.type === mime
            ? file
            : new File([file], file.name, { type: mime });
        const { key } = await presignAndUpload(named, {});
        onUploaded({
          key,
          name: file.name,
          sizeLabel: formatBytes(file.size),
        });
        setStatus("done");
      } catch (err) {
        setStatus("error");
        setError(
          friendlyErrorMessage(err, "Upload failed. Please try again."),
        );
      }
    },
    [onUploaded],
  );

  const onPick = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    // Allow re-picking the same file after an error.
    event.target.value = "";
    if (file) void upload(file);
  };

  if (value && status === "done") {
    return (
      <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/40 p-4">
        <div className="flex min-w-0 items-center gap-3">
          <CheckCircle2 className="size-5 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{value.name}</p>
            <p className="text-xs text-muted-foreground">
              {value.sizeLabel} — narration uploaded
            </p>
          </div>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            onClear();
            setStatus("idle");
          }}
        >
          <X className="size-4" aria-hidden /> Replace
        </Button>
      </div>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const file = e.dataTransfer.files?.[0];
          if (file) void upload(file);
        }}
        disabled={status === "uploading"}
        className={cn(
          "flex w-full flex-col items-center gap-2 rounded-lg border-2 border-dashed border-border p-8 text-center transition-colors",
          dragOver && "border-primary bg-primary/5",
          status === "uploading" && "cursor-wait opacity-70",
        )}
        aria-label="Upload narration audio"
      >
        {status === "uploading" ? (
          <Loader2 className="size-6 animate-spin text-primary" aria-hidden />
        ) : (
          <UploadCloud className="size-6 text-muted-foreground" aria-hidden />
        )}
        <span className="text-sm font-medium">
          {status === "uploading"
            ? "Uploading narration…"
            : "Drop your narration here, or click to browse"}
        </span>
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <FileAudio className="size-3.5" aria-hidden /> WAV or MP3 — your own
          voice memo works great
        </span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT_ATTR}
        className="sr-only"
        onChange={onPick}
        tabIndex={-1}
      />
      {status === "error" && error && (
        <p className="mt-2 flex items-center gap-1.5 text-sm text-destructive">
          <AlertCircle className="size-4 shrink-0" aria-hidden /> {error}
        </p>
      )}
    </div>
  );
}
