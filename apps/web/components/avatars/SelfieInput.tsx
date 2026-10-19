"use client";

import * as React from "react";
import { AlertCircle, ImagePlus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** A selected selfie plus an object-URL preview owned by {@link SelfieInput}. */
export interface SelfiePhoto {
  file: File;
  previewUrl: string;
}

interface SelfieInputProps {
  value: SelfiePhoto | null;
  onChange: (photo: SelfiePhoto | null) => void;
  disabled?: boolean;
}

const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"] as const;
const MAX_BYTES = 12 * 1024 * 1024; // 12 MB

function validate(file: File): string | null {
  if (!file.type.startsWith("image/")) {
    return "Please choose an image file (JPG, PNG, or WebP).";
  }
  if (!(ACCEPTED_TYPES as readonly string[]).includes(file.type)) {
    return "Unsupported image format. Use JPG, PNG, or WebP.";
  }
  if (file.size <= 0) return "That file looks empty.";
  if (file.size > MAX_BYTES) return "Image is too large (max 12 MB).";
  return null;
}

/**
 * Controlled selfie picker: validates an image file, shows a square preview, and
 * reports the chosen file up with an object-URL preview. The object URL is
 * revoked when the selection changes or the component unmounts (no leaks).
 */
export function SelfieInput({ value, onChange, disabled }: SelfieInputProps) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const urlRef = React.useRef<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [isDragging, setIsDragging] = React.useState(false);

  // Revoke the last object URL we created on unmount.
  React.useEffect(() => {
    return () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, []);

  const selectFile = React.useCallback(
    (file: File | undefined) => {
      if (!file) return;
      const validationError = validate(file);
      if (validationError) {
        setError(validationError);
        return;
      }
      setError(null);
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      const previewUrl = URL.createObjectURL(file);
      urlRef.current = previewUrl;
      onChange({ file, previewUrl });
    },
    [onChange],
  );

  const handleClear = React.useCallback(() => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
    onChange(null);
  }, [onChange]);

  if (value) {
    return (
      <div className="flex items-center gap-4 rounded-lg border border-border bg-secondary/20 p-3">
        <span className="relative block size-20 shrink-0 overflow-hidden rounded-md bg-secondary">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={value.previewUrl}
            alt="Selected selfie preview"
            className="size-full object-cover"
          />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{value.file.name}</p>
          <p className="text-xs text-muted-foreground">Ready to upload</p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={handleClear}
          disabled={disabled}
          aria-label="Remove selected photo"
        >
          <X /> Replace
        </Button>
      </div>
    );
  }

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload a selfie photo"
        aria-disabled={disabled}
        onClick={() => {
          if (!disabled) inputRef.current?.click();
        }}
        onKeyDown={(e) => {
          if (disabled) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          if (!disabled) selectFile(e.dataTransfer.files?.[0]);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-8 text-center transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          disabled && "pointer-events-none opacity-60",
          isDragging
            ? "border-primary bg-primary/10"
            : "border-border bg-secondary/20 hover:border-primary/60 hover:bg-secondary/40",
        )}
      >
        <span className="flex size-11 items-center justify-center rounded-full bg-primary/15 text-primary">
          <ImagePlus className="size-5" aria-hidden />
        </span>
        <div>
          <p className="text-sm font-medium">Add a clear selfie</p>
          <p className="text-xs text-muted-foreground">
            Front-facing, well-lit — JPG, PNG, or WebP up to 12 MB
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="sr-only"
          disabled={disabled}
          onChange={(e) => selectFile(e.target.files?.[0])}
        />
      </div>

      {error && (
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
