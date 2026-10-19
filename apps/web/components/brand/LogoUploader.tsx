"use client";

import * as React from "react";
import { AlertCircle, ImagePlus, Trash2, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LOGO_ACCEPT, MAX_LOGO_BYTES } from "@/components/brand/brand-utils";

/** A locally-selected logo file plus an object URL for preview. */
export interface LogoSelection {
  file: File;
  /** `URL.createObjectURL` handle for the preview (the parent revokes it). */
  url: string;
}

interface LogoUploaderProps {
  /** Local object URL of a freshly-picked logo, if any. */
  pendingUrl: string | null;
  /** Presigned URL of the already-stored logo, if any. */
  storedUrl: string | null;
  /** Reports a newly-picked logo up (parent uploads it on save). */
  onSelect: (selection: LogoSelection) => void;
  /** Clears the pending pick and/or the stored logo. */
  onClear: () => void;
  disabled?: boolean;
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
 * Lets the creator pick a transparent-PNG logo. Validates the type + size at the
 * boundary, shows a small preview on a checkerboard so transparency is visible,
 * and reports the `File` up — the parent owns the object-URL lifecycle and
 * handles presign + upload on save.
 */
export function LogoUploader({
  pendingUrl,
  storedUrl,
  onSelect,
  onClear,
  disabled = false,
}: LogoUploaderProps) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [error, setError] = React.useState<string | null>(null);

  const onPickFile = React.useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      // Allow re-picking the same file later by clearing the input value.
      if (inputRef.current) inputRef.current.value = "";
      if (!file) return;
      setError(null);
      if (file.type !== "image/png") {
        setError("Please choose a transparent PNG logo.");
        return;
      }
      if (file.size <= 0) {
        setError("That file looks empty.");
        return;
      }
      if (file.size > MAX_LOGO_BYTES) {
        setError(`Logo is too large (max ${formatBytes(MAX_LOGO_BYTES)}).`);
        return;
      }
      onSelect({ file, url: URL.createObjectURL(file) });
    },
    [onSelect],
  );

  const clear = React.useCallback(() => {
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
    onClear();
  }, [onClear]);

  const previewUrl = pendingUrl ?? storedUrl;

  return (
    <div className="space-y-3">
      {previewUrl ? (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-secondary/20 p-4">
          <div
            className="flex size-20 shrink-0 items-center justify-center rounded-md border border-border"
            style={{
              backgroundImage:
                "linear-gradient(45deg, hsl(var(--muted)) 25%, transparent 25%), linear-gradient(-45deg, hsl(var(--muted)) 25%, transparent 25%), linear-gradient(45deg, transparent 75%, hsl(var(--muted)) 75%), linear-gradient(-45deg, transparent 75%, hsl(var(--muted)) 75%)",
              backgroundSize: "12px 12px",
              backgroundPosition: "0 0, 0 6px, 6px -6px, -6px 0px",
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- user logo, local/presigned URL */}
            <img
              src={previewUrl}
              alt="Brand logo preview"
              className="max-h-full max-w-full object-contain p-1"
            />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {pendingUrl ? "New logo selected" : "Current logo"}
            </p>
            <p className="text-xs text-muted-foreground">
              {pendingUrl
                ? "Saved when you apply your changes."
                : "Transparent PNG stored on your brand."}
            </p>
          </div>
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
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={disabled}
          className="flex w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-secondary/20 p-8 text-center transition-colors hover:bg-secondary/40 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span className="flex size-10 items-center justify-center rounded-full bg-primary/10">
            <ImagePlus className="size-5 text-primary" aria-hidden />
          </span>
          <span className="text-sm font-medium">Upload a logo</span>
          <span className="text-xs text-muted-foreground">
            Transparent PNG, max {formatBytes(MAX_LOGO_BYTES)}
          </span>
        </button>
      )}

      {previewUrl && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => inputRef.current?.click()}
          disabled={disabled}
        >
          <UploadCloud /> Replace logo
        </Button>
      )}

      <input
        ref={inputRef}
        type="file"
        accept={LOGO_ACCEPT}
        className="sr-only"
        onChange={(e) => onPickFile(e.target.files)}
      />

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
