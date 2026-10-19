"use client";

import * as React from "react";
import { AlertCircle, Loader2, Mic, RefreshCw, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { VoiceVerificationPhrase } from "@/lib/types";

/** The live recording of the verification phrase, with the token it answers. */
export interface VerificationTake {
  file: File;
  url: string;
  token: string;
}

interface VerificationRecorderProps {
  /** Fetches a fresh phrase (POST /voices/verification-phrase). */
  loadPhrase: () => Promise<VoiceVerificationPhrase>;
  value: VerificationTake | null;
  onChange: (take: VerificationTake | null) => void;
  disabled?: boolean;
}

const MIN_SECONDS = 2;

function mimeForRecorder(): string {
  if (typeof MediaRecorder === "undefined") return "";
  return ["audio/webm", "audio/mp4", "audio/ogg"].find((m) => MediaRecorder.isTypeSupported(m)) ?? "";
}

function extFor(mime: string): string {
  if (mime.includes("mp4")) return "m4a";
  if (mime.includes("ogg")) return "ogg";
  return "webm";
}

/**
 * M7.2: live voice check. Shows a one-off phrase and records the creator
 * reading it (microphone only; no file upload, so it has to be live). The
 * server checks the words and that the speaker matches the voice sample.
 */
export function VerificationRecorder({ loadPhrase, value, onChange, disabled = false }: VerificationRecorderProps) {
  const [phrase, setPhrase] = React.useState<VoiceVerificationPhrase | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [recording, setRecording] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const recorderRef = React.useRef<MediaRecorder | null>(null);
  const chunksRef = React.useRef<Blob[]>([]);
  const startedRef = React.useRef(0);
  const urlRef = React.useRef<string | null>(null);

  const publish = React.useCallback(
    (next: VerificationTake | null) => {
      if (urlRef.current && urlRef.current !== next?.url) URL.revokeObjectURL(urlRef.current);
      urlRef.current = next?.url ?? null;
      onChange(next);
    },
    [onChange],
  );

  const fetchPhrase = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    publish(null);
    try {
      setPhrase(await loadPhrase());
    } catch {
      setError("Could not get a phrase. Try again.");
    } finally {
      setLoading(false);
    }
  }, [loadPhrase, publish]);

  React.useEffect(() => {
    void fetchPhrase();
    return () => {
      recorderRef.current?.stream.getTracks().forEach((t) => t.stop());
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
    // Load one phrase on mount only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const start = React.useCallback(async () => {
    if (!phrase) return;
    setError(null);
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("Recording is not supported in this browser. Use a current version of Chrome, Safari or Firefox.");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Microphone access was blocked. Allow it to verify your voice.");
      return;
    }
    const mime = mimeForRecorder();
    const recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    recorderRef.current = recorder;
    chunksRef.current = [];
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      const type = recorder.mimeType || mime || "audio/webm";
      const blob = new Blob(chunksRef.current, { type });
      chunksRef.current = [];
      if (blob.size <= 0 || (Date.now() - startedRef.current) / 1000 < MIN_SECONDS) {
        setError("That recording was too short. Read the whole phrase.");
        return;
      }
      const file = new File([blob], `voice-check-${Date.now()}.${extFor(type)}`, { type });
      publish({ file, url: URL.createObjectURL(blob), token: phrase.token });
    };
    publish(null);
    startedRef.current = Date.now();
    recorder.start();
    setRecording(true);
  }, [phrase, publish]);

  const stop = React.useCallback(() => {
    setRecording(false);
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }, []);

  return (
    <div className="space-y-3 rounded-lg border border-border p-4">
      <p className="text-sm text-muted-foreground">
        Read this phrase out loud in the same voice as your sample. It proves the voice is yours.
      </p>
      <div className="flex items-center justify-between gap-3">
        <p className="font-mono text-base" data-testid="verification-phrase">
          {loading ? "Loading phrase..." : phrase?.phrase ?? ""}
        </p>
        <Button type="button" variant="ghost" size="sm" onClick={() => void fetchPhrase()} disabled={disabled || loading || recording}>
          <RefreshCw aria-hidden /> New phrase
        </Button>
      </div>
      <div className="flex items-center gap-3">
        {recording ? (
          <Button type="button" variant="destructive" onClick={stop}>
            <Square aria-hidden /> Stop
          </Button>
        ) : (
          <Button type="button" variant="secondary" onClick={() => void start()} disabled={disabled || loading || !phrase}>
            {loading ? <Loader2 className="animate-spin" aria-hidden /> : <Mic aria-hidden />}
            {value ? "Record again" : "Record the phrase"}
          </Button>
        )}
        {value && !recording ? <audio controls src={value.url} className="h-9" aria-label="Your verification recording" /> : null}
      </div>
      {error ? (
        <p role="alert" className="flex items-center gap-2 text-sm text-destructive">
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          {error}
        </p>
      ) : null}
    </div>
  );
}
