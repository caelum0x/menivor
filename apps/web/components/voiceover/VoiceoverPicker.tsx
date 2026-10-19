"use client";

import * as React from "react";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { ApiError, presignAndUpload } from "@/lib/api";
import { Progress } from "@/components/ui/progress";
import { useApiToken } from "@/lib/use-api-token";
import {
  AudioSampleInput,
  type AudioSample,
} from "@/components/voices/AudioSampleInput";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** The uploaded voiceover, mirrored into wizard state. */
export interface UploadedVoiceover {
  /** R2 object key -> `voiceover_key` on the job. */
  key: string;
  /** Presigned GET URL for previewing the uploaded audio. */
  url: string;
  /** Original file / take name, shown in the review summary. */
  name: string;
}

interface VoiceoverPickerProps {
  value: UploadedVoiceover | null;
  onUploaded: (voiceover: UploadedVoiceover) => void;
  onClear: () => void;
}

type Phase =
  | { status: "idle" }
  | { status: "uploading"; progress: number }
  | { status: "done" }
  | { status: "error"; message: string };

/**
 * BRING YOUR OWN VOICEOVER capture: the creator records (MediaRecorder) or
 * uploads their OWN narration audio, which is presigned + PUT to R2 via
 * {@link presignAndUpload}. The resulting object key is reported up as the reel's
 * `voiceover_key`; the backend transcribes the same audio to drive captions and
 * the avatar lip-sync. Reuses {@link AudioSampleInput} for the record/upload UI.
 */
export function VoiceoverPicker({
  value,
  onUploaded,
  onClear,
}: VoiceoverPickerProps) {
  const getApiToken = useApiToken();
  // Local capture (a File + object URL) before it is uploaded to R2.
  const [sample, setSample] = React.useState<AudioSample | null>(null);
  const [phase, setPhase] = React.useState<Phase>(
    value ? { status: "done" } : { status: "idle" },
  );
  const abortRef = React.useRef<AbortController | null>(null);

  React.useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const upload = React.useCallback(
    async (next: AudioSample) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setPhase({ status: "uploading", progress: 0 });
      try {
        const token = await getApiToken();
        const result = await presignAndUpload(next.file, {
          token,
          signal: controller.signal,
          onProgress: (fraction) =>
            setPhase({ status: "uploading", progress: Math.round(fraction * 100) }),
        });
        setPhase({ status: "done" });
        onUploaded({
          key: result.key,
          url: result.get_url,
          name: next.source === "recorded" ? "Recorded voiceover" : next.file.name,
        });
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        const message =
          friendlyErrorMessage(err, "Could not upload your voiceover. Please try again.");
        setPhase({ status: "error", message });
      }
    },
    [getApiToken, onUploaded],
  );

  const handleSampleChange = React.useCallback(
    (next: AudioSample | null) => {
      setSample(next);
      if (!next) {
        abortRef.current?.abort();
        setPhase({ status: "idle" });
        onClear();
        return;
      }
      void upload(next);
    },
    [onClear, upload],
  );

  const uploading = phase.status === "uploading";

  return (
    <div className="space-y-3">
      <AudioSampleInput
        value={sample}
        onChange={handleSampleChange}
        disabled={uploading}
      />

      {uploading && (
        <div className="space-y-2">
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
            Uploading voiceover… {phase.progress}%
          </p>
          <Progress value={phase.progress} />
        </div>
      )}

      {phase.status === "done" && value && (
        <p className="flex items-center gap-2 text-sm text-success">
          <CheckCircle2 className="size-4 shrink-0" aria-hidden />
          Voiceover uploaded — captions will be generated from it.
        </p>
      )}

      {phase.status === "error" && (
        <p
          role="alert"
          className="flex items-center gap-2 text-sm text-destructive"
        >
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          {phase.message}
        </p>
      )}
    </div>
  );
}
