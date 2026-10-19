"use client";

import * as React from "react";
import { Loader2, Upload, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { presignAndUpload } from "@/lib/api";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

import { GARMENT_FILE_TYPES } from "../model";

export interface ImageUploadFieldProps {
  readonly id: string;
  readonly label: string;
  readonly hint: string;
  /** The uploaded "uploads/..." key, or undefined when none. */
  readonly value: string | undefined;
  readonly readyText: string;
  readonly previewAlt: string;
  /** Plain sentence when the file is not acceptable, "" when it is. */
  readonly problemFor: (file: File) => string;
  readonly onChange: (key: string | undefined) => void;
  readonly onUploading?: (uploading: boolean) => void;
}

/** One optional image upload through the existing presign path, with a preview and a remove button. */
export function ImageUploadField({
  id,
  label,
  hint,
  value,
  readyText,
  previewAlt,
  problemFor,
  onChange,
  onUploading,
}: ImageUploadFieldProps) {
  const getApiToken = useApiToken();
  const [preview, setPreview] = React.useState("");
  const [uploading, setUploading] = React.useState(false);
  const [problem, setProblem] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement>(null);

  const setBusy = (busy: boolean) => {
    setUploading(busy);
    onUploading?.(busy);
  };

  const upload = async (file: File) => {
    const why = problemFor(file);
    setProblem(why);
    if (why) return;
    setBusy(true);
    try {
      const result = await presignAndUpload(file, { token: await getApiToken() });
      setPreview(result.get_url);
      onChange(result.key);
    } catch (err) {
      setProblem(friendlyErrorMessage(err, "The file could not be uploaded. Try again."));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const remove = () => {
    setPreview("");
    setProblem("");
    onChange(undefined);
  };

  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <p className="text-xs text-muted-foreground">{hint}</p>
      {value ? (
        <div className="flex items-center gap-3">
          {preview ? (
            // eslint-disable-next-line @next/next/no-img-element -- presigned media URL
            <img src={preview} alt={previewAlt} className="size-16 rounded-lg object-cover" />
          ) : null}
          <span className="text-sm" data-testid={`${id}-ready`}>{readyText}</span>
          <Button type="button" variant="ghost" size="sm" onClick={remove}>
            <X className="size-4" aria-hidden /> Remove
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-3">
          <input
            ref={inputRef}
            id={id}
            type="file"
            accept={GARMENT_FILE_TYPES.join(",")}
            className="sr-only"
            disabled={uploading}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void upload(file);
            }}
          />
          <Button type="button" variant="outline" disabled={uploading} onClick={() => inputRef.current?.click()}>
            {uploading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Upload className="size-4" aria-hidden />}
            {uploading ? "Uploading" : "Choose a file"}
          </Button>
        </div>
      )}
      {problem ? <p role="alert" className="text-sm text-destructive">{problem}</p> : null}
    </div>
  );
}
