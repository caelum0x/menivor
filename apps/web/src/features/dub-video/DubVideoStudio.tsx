"use client";

import * as React from "react";
import Link from "next/link";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Send,
  UploadCloud,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import { ApiError, presignAndUpload } from "@/lib/api";
import { listUploads, type UploadAsset } from "@/lib/library-api";
import { useApiToken } from "@/lib/use-api-token";
import { POLL_INTERVAL_MS } from "@/src/shared/api";

import {
  createDub,
  getDub,
  getDubOptions,
  isTerminalDub,
  languageLabel,
  listDubs,
  type DubJob,
  type DubOptions,
} from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

function messageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err, fallback);
  if (err instanceof Error) return friendlyErrorMessage(err, fallback);
  return fallback;
}

function formatMinutes(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  return `${minutes} min`;
}

type VoiceEngine = "edge" | "elevenlabs";

/**
 * Dub Studio: upload (or pick) a video, choose the spoken language and the
 * language to dub into, pick a voice, and follow the dub to a downloadable
 * video with subtitle files. Free voices (edge-tts) and on-server speech
 * recognition are the default; ElevenLabs appears only when configured.
 */
export function DubVideoStudio() {
  const getToken = useApiToken();
  const [options, setOptions] = React.useState<DubOptions | null>(null);
  const [loadError, setLoadError] = React.useState("");
  const [videos, setVideos] = React.useState<readonly UploadAsset[]>([]);
  const [dubs, setDubs] = React.useState<readonly DubJob[]>([]);

  const [videoKey, setVideoKey] = React.useState("");
  const [uploadName, setUploadName] = React.useState("");
  const [uploadProgress, setUploadProgress] = React.useState<number | null>(null);
  const [source, setSource] = React.useState("en");
  const [target, setTarget] = React.useState("tr");
  const [engine, setEngine] = React.useState<VoiceEngine>("edge");
  const [voice, setVoice] = React.useState("");
  const [elevenVoice, setElevenVoice] = React.useState("");
  const [model, setModel] = React.useState("small");
  const [submitting, setSubmitting] = React.useState(false);
  const [formError, setFormError] = React.useState("");
  const fileInput = React.useRef<HTMLInputElement>(null);

  const load = React.useCallback(async () => {
    setLoadError("");
    try {
      const token = await getToken();
      const [opts, history, uploads] = await Promise.all([
        getDubOptions({ token }),
        listDubs(20, { token }),
        listUploads({ kind: "video", limit: 50 }, { token }),
      ]);
      setOptions(opts);
      setModel(opts.default_whisper_model || "small");
      setDubs(history);
      setVideos(uploads.uploads);
    } catch (err) {
      setLoadError(messageOf(err, "Couldn't load the dub studio."));
    }
  }, [getToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  // Poll every non-terminal dub until it completes or fails.
  const pendingIds = React.useMemo(
    () => dubs.filter((d) => !isTerminalDub(d)).map((d) => d.dub_id),
    [dubs],
  );
  React.useEffect(() => {
    if (pendingIds.length === 0) return undefined;
    const timer = window.setInterval(async () => {
      const token = await getToken();
      const fresh = await Promise.all(
        pendingIds.map((id) => getDub(id, { token }).catch(() => null)),
      );
      setDubs((prev) =>
        prev.map((d) => fresh.find((f) => f && f.dub_id === d.dub_id) ?? d),
      );
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [pendingIds, getToken]);

  const languages = options?.languages ?? [];
  const targetVoices = React.useMemo(
    () => languages.find((l) => l.code === target)?.voices ?? [],
    [languages, target],
  );
  const elevenAvailable =
    options?.voice_engines.find((e) => e.id === "elevenlabs")?.available ?? false;
  const free = engine === "edge";
  const cost = options ? (free ? options.costs.free : options.costs.premium) : 0;
  const premiumVoiceCredits = !free && options ? (options.costs.premium_voice_credits ?? 0) : 0;

  React.useEffect(() => {
    // Keep the chosen free voice valid for the target language.
    setVoice((current) => (targetVoices.includes(current) ? current : targetVoices[0] ?? ""));
  }, [targetVoices]);

  const onFile = React.useCallback(
    async (file: File | undefined) => {
      if (!file) return;
      setFormError("");
      if (!file.type.startsWith("video/")) {
        setFormError("Choose a video file.");
        return;
      }
      if (options && options.max_bytes && file.size > options.max_bytes) {
        setFormError(`That file is over ${Math.round(options.max_bytes / (1024 * 1024))} MB.`);
        return;
      }
      setUploadName(file.name);
      setUploadProgress(0);
      try {
        const token = await getToken();
        const result = await presignAndUpload(file, {
          token,
          onProgress: (f) => setUploadProgress(Math.round(f * 100)),
        });
        setVideoKey(result.key);
        setUploadProgress(100);
      } catch (err) {
        setUploadProgress(null);
        setUploadName("");
        setFormError(messageOf(err, "Upload failed. Check your connection and try again."));
      }
    },
    [getToken, options],
  );

  const submit = React.useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      setFormError("");
      if (!videoKey) {
        setFormError("Upload a video or pick one you already uploaded.");
        return;
      }
      if (source === target) {
        setFormError("Pick a different language to dub into.");
        return;
      }
      if (engine === "elevenlabs" && !elevenVoice.trim()) {
        setFormError("Enter an ElevenLabs voice name.");
        return;
      }
      setSubmitting(true);
      try {
        const token = await getToken();
        const job = await createDub(
          {
            video_key: videoKey,
            source_language: source,
            target_language: target,
            voice_engine: engine,
            voice: engine === "edge" ? voice : elevenVoice.trim(),
            whisper_model: model,
          },
          { token },
        );
        setDubs((prev) => [job, ...prev.filter((d) => d.dub_id !== job.dub_id)]);
      } catch (err) {
        setFormError(messageOf(err, "Couldn't start the dub."));
      } finally {
        setSubmitting(false);
      }
    },
    [videoKey, source, target, engine, voice, elevenVoice, model, getToken],
  );

  if (loadError) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-6 text-sm">
          <AlertCircle className="h-5 w-5 text-destructive" aria-hidden />
          <span>{loadError}</span>
          <Button size="sm" variant="outline" onClick={() => void load()}>
            Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (!options) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading
      </div>
    );
  }

  const disabled = !options.available || submitting;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,420px)_1fr]">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">New dub</CardTitle>
        </CardHeader>
        <CardContent>
          {!options.available && (
            <p className="mb-4 rounded-md border border-border bg-secondary/40 p-3 text-sm text-muted-foreground">
              Dubbing is not switched on for this server yet. The dubbing engine runs as a separate
              service that the operator has to set up first.
            </p>
          )}
          <form className="space-y-4" onSubmit={submit}>
            <div className="space-y-2">
              <Label>Video</Label>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={disabled}
                  onClick={() => fileInput.current?.click()}
                >
                  <UploadCloud className="mr-1.5 h-4 w-4" aria-hidden /> Upload video
                </Button>
                <input
                  ref={fileInput}
                  type="file"
                  accept="video/*"
                  className="hidden"
                  onChange={(e) => void onFile(e.target.files?.[0])}
                />
              </div>
              {uploadProgress !== null && (
                <div className="space-y-1">
                  <p className="truncate text-xs text-muted-foreground">{uploadName}</p>
                  <Progress value={uploadProgress} />
                </div>
              )}
              {videos.length > 0 && (
                <Select
                  aria-label="Or pick a video you already uploaded"
                  value={videos.some((v) => v.key === videoKey) ? videoKey : ""}
                  disabled={disabled}
                  onChange={(e) => {
                    setVideoKey(e.target.value);
                    setUploadProgress(null);
                    setUploadName("");
                  }}
                >
                  <option value="">Or pick an uploaded video</option>
                  {videos.map((v) => (
                    <option key={v.asset_id} value={v.key}>
                      {v.filename || v.key}
                    </option>
                  ))}
                </Select>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="dub-source">Spoken language</Label>
                <Select id="dub-source" value={source} disabled={disabled} onChange={(e) => setSource(e.target.value)}>
                  {languages.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.label}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="dub-target">Dub into</Label>
                <Select id="dub-target" value={target} disabled={disabled} onChange={(e) => setTarget(e.target.value)}>
                  {languages.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.label}
                    </option>
                  ))}
                </Select>
              </div>
            </div>

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Voice</legend>
              {options.voice_engines.map((e) => (
                <label key={e.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="dub-engine"
                    value={e.id}
                    checked={engine === e.id}
                    disabled={disabled || !e.available}
                    onChange={() => setEngine(e.id)}
                  />
                  <span>{e.label}</span>
                  {!e.available && <span className="text-xs text-muted-foreground">(not configured)</span>}
                </label>
              ))}
              {engine === "edge" ? (
                <Select aria-label="Free voice" value={voice} disabled={disabled} onChange={(e) => setVoice(e.target.value)}>
                  {targetVoices.map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  aria-label="ElevenLabs voice name"
                  placeholder="ElevenLabs voice name"
                  value={elevenVoice}
                  maxLength={64}
                  disabled={disabled || !elevenAvailable}
                  onChange={(e) => setElevenVoice(e.target.value)}
                />
              )}
            </fieldset>

            <div className="space-y-2">
              <Label htmlFor="dub-model">Speech recognition accuracy</Label>
              <Select id="dub-model" value={model} disabled={disabled} onChange={(e) => setModel(e.target.value)}>
                {options.whisper_models.map((m) => (
                  <option key={m} value={m}>
                    {m === "tiny" ? "tiny (fastest)" : m === "medium" ? "medium (slowest, most accurate)" : m}
                  </option>
                ))}
              </Select>
            </div>

            <p className="text-xs text-muted-foreground">
              {free
                ? "Free voices and on-server speech recognition, no paid API involved. "
                : "ElevenLabs voices are a paid API. "}
              This dub costs {cost} credit{cost === 1 ? "" : "s"}
              {premiumVoiceCredits > 0
                ? ` and ${premiumVoiceCredits} premium voice credit${premiumVoiceCredits === 1 ? "" : "s"}`
                : ""}
              ; credits come back if it fails.
              Up to {formatMinutes(options.max_seconds)} per video. Subtitles are translated with{" "}
              {options.translation === "relay" ? "our AI model" : "Google Translate"}.
            </p>

            {formError && (
              <p role="alert" className="flex items-center gap-2 text-sm text-destructive">
                <AlertCircle className="h-4 w-4" aria-hidden /> {formError}
              </p>
            )}
            <Button type="submit" disabled={disabled || !videoKey}>
              {submitting && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" aria-hidden />}
              Start dub
            </Button>
          </form>
        </CardContent>
      </Card>

      <section aria-label="Your dubs" className="space-y-3">
        <h2 className="text-sm font-medium">Your dubs</h2>
        {dubs.length === 0 && (
          <p className="text-sm text-muted-foreground">No dubs yet. Finished dubs show up here.</p>
        )}
        {dubs.map((d) => (
          <DubCard key={d.dub_id} job={d} languages={options.languages} />
        ))}
      </section>
    </div>
  );
}

function DubCard({ job, languages }: { job: DubJob; languages: DubOptions["languages"] }) {
  const title = `${languageLabel(languages, job.source_language)} to ${languageLabel(languages, job.target_language)}`;
  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            {job.state === "complete" && <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden />}
            {job.state === "failed" && <AlertCircle className="h-4 w-4 text-destructive" aria-hidden />}
            {job.state === "processing" && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
            <span className="text-sm font-medium">{title}</span>
            <span className="text-xs text-muted-foreground">{job.voice}</span>
          </div>
          <Badge variant="secondary">{job.free ? "Free voice" : "ElevenLabs"}</Badge>
        </div>

        {job.state === "processing" && (
          <div className="space-y-1">
            <Progress value={job.progress} />
            <p className="text-xs text-muted-foreground">
              Transcribing, translating and re-voicing. A few minutes per minute of video.
            </p>
          </div>
        )}

        {job.state === "failed" && (
          <p className="text-sm text-destructive">
            {job.error || "The dub failed."} {job.refunded ? "Your credits were refunded." : ""}
          </p>
        )}

        {job.state === "complete" && (
          <div className="space-y-3">
            {job.video_url && (
              <video src={job.video_url} controls preload="metadata" className="w-full max-w-md rounded-md" />
            )}
            <div className="flex flex-wrap gap-2">
              {job.video_url && (
                <Button asChild size="sm" variant="outline">
                  <a href={job.video_url} download>
                    <Download className="mr-1.5 h-4 w-4" aria-hidden /> Video
                  </a>
                </Button>
              )}
              {job.subtitles.map((s) => (
                <Button key={s.key} asChild size="sm" variant="outline">
                  <a href={s.url} download>
                    <FileText className="mr-1.5 h-4 w-4" aria-hidden />
                    {languageLabel(languages, s.language)} subtitles
                  </a>
                </Button>
              ))}
              <Button asChild size="sm">
                <Link href={`/publish?job=${encodeURIComponent(job.dub_id)}`}>
                  <Send className="mr-1.5 h-4 w-4" aria-hidden /> Publish
                </Link>
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
