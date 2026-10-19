"use client";

// Reel-create presentation component.

import * as React from "react";
import {
  AlertCircle,
  CheckCircle2,
  FileVideo,
  Loader2,
  UploadCloud,
  X,
} from "lucide-react";
import { ApiError, presignAndUpload } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { useApiToken } from "@/lib/use-api-token";
import { MAX_UPLOAD_BYTES } from "@/components/wizard/types";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface UploadedRecording {
  key: string;
  url: string;
  name: string;
}

interface UploadDropzoneProps {
  value: UploadedRecording | null;
  onUploaded: (recording: UploadedRecording) => void;
  onClear: () => void;
}

type Status = "idle" | "uploading" | "done" | "error";

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

function validateFile(file: File): string | null {
  if (!file.type.startsWith("video/")) {
    return "Please choose a video file (screen recording).";
  }
  if (file.size <= 0) {
    return "That file looks empty.";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return `File is too large (max ${formatBytes(MAX_UPLOAD_BYTES)}).`;
  }
  return null;
}

/**
 * Drag-and-drop uploader for the screen recording. Presigns and PUTs the file
 * via `lib/api.presignAndUpload`, surfacing progress and errors, and reports
 * the resulting R2 key up to the wizard.
 */
export function UploadDropzone({
  value,
  onUploaded,
  onClear,
}: UploadDropzoneProps) {
  const getApiToken = useApiToken();
  const inputRef = React.useRef<HTMLInputElement>(null);
  const abortRef = React.useRef<AbortController | null>(null);

  const [status, setStatus] = React.useState<Status>(value ? "done" : "idle");
  const [progress, setProgress] = React.useState(value ? 100 : 0);
  const [error, setError] = React.useState<string | null>(null);
  const [isDragging, setIsDragging] = React.useState(false);
  const [pendingName, setPendingName] = React.useState<string | null>(null);

  React.useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const startUpload = React.useCallback(
    async (file: File) => {
      const validationError = validateFile(file);
      if (validationError) {
        setError(validationError);
        setStatus("error");
        return;
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setError(null);
      setPendingName(file.name);
      setProgress(0);
      setStatus("uploading");

      try {
        const token = await getApiToken();
        const result = await presignAndUpload(file, {
          token,
          signal: controller.signal,
          onProgress: (fraction) =>
            setProgress(Math.round(fraction * 100)),
        });
        setProgress(100);
        setStatus("done");
        onUploaded({ key: result.key, url: result.get_url, name: file.name });
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          // Cancelled by the user or a superseding upload; stay silent.
          return;
        }
        const message =
          friendlyErrorMessage(err, "Upload failed. Please check your connection and try again.");
        setError(message);
        setStatus("error");
      }
    },
    [getApiToken, onUploaded],
  );

  const onFiles = React.useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (file) void startUpload(file);
    },
    [startUpload],
  );

  const handleDrop = React.useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setIsDragging(false);
      onFiles(event.dataTransfer.files);
    },
    [onFiles],
  );

  const handleClear = React.useCallback(() => {
    abortRef.current?.abort();
    setStatus("idle");
    setProgress(0);
    setError(null);
    setPendingName(null);
    if (inputRef.current) inputRef.current.value = "";
    onClear();
  }, [onClear]);

  // ----- Completed state -----
  if (status === "done" && value) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-success/40 bg-success/5 p-4">
        <CheckCircle2 className="size-6 shrink-0 text-success" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{value.name}</p>
          <p className="text-xs text-success">Upload complete.</p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={handleClear}
          aria-label="Remove uploaded recording"
        >
          <X /> Replace
        </Button>
      </div>
    );
  }

  // ----- Uploading state -----
  if (status === "uploading") {
    return (
      <div className="rounded-lg border border-border bg-card p-5">
        <div className="mb-3 flex items-center gap-3">
          <Loader2
            className="size-5 shrink-0 animate-spin text-primary"
            aria-hidden
          />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {pendingName ?? "Uploading…"}
            </p>
            <p className="text-xs text-muted-foreground">
              Uploading to secure storage… {progress}%
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleClear}
          >
            Cancel
          </Button>
        </div>
        <Progress value={progress} />
      </div>
    );
  }

  // ----- Idle / error state (dropzone) -----
  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload screen recording"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-10 text-center transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          isDragging
            ? "border-primary bg-primary/10"
            : "border-border bg-secondary/20 hover:border-primary/60 hover:bg-secondary/40",
        )}
      >
        <span className="flex size-12 items-center justify-center rounded-full bg-primary/15 text-primary">
          {status === "error" ? (
            <FileVideo className="size-6" aria-hidden />
          ) : (
            <UploadCloud className="size-6" aria-hidden />
          )}
        </span>
        <div>
          <p className="text-sm font-medium">
            Drag &amp; drop your screen recording
          </p>
          <p className="text-xs text-muted-foreground">
            or click to browse — MP4/MOV/WebM up to{" "}
            {formatBytes(MAX_UPLOAD_BYTES)}
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="video/*"
          className="sr-only"
          onChange={(e) => onFiles(e.target.files)}
        />
      </div>

      {status === "error" && error && (
        <p
          role="alert"
          className="mt-3 flex items-center gap-2 text-sm text-destructive"
        >
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          {error}
        </p>
      )}
    </div>
  );
}
