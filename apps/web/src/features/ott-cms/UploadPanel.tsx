"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { useApiToken } from "@/lib/use-api-token";
import { ApiError } from "@/src/shared/api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { completeUpload, forgetUpload, uploadFile } from "./uploader";

function mediaInfo(file: File): Promise<{ seconds: number; shortSide: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const el = document.createElement(file.type.startsWith("audio/") ? "audio" : "video");
    el.preload = "metadata";
    el.onloadedmetadata = () => {
      const video = el as HTMLVideoElement;
      resolve({ seconds: el.duration, shortSide: Math.min(video.videoWidth || 0, video.videoHeight || 0) });
      URL.revokeObjectURL(url);
    };
    el.onerror = () => reject(new Error("We could not read that file."));
    el.src = url;
  });
}

/** Long-form upload: resumes after a reload; the title is queued for packaging when it lands. */
export function UploadPanel({ onDone }: Readonly<{ onDone?: () => void }>) {
  const getApiToken = useApiToken();
  const [file, setFile] = React.useState<File | null>(null);
  const [title, setTitle] = React.useState("");
  const [progress, setProgress] = React.useState(0);
  const [status, setStatus] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [overQuota, setOverQuota] = React.useState(false);

  async function onUpload(event: React.FormEvent) {
    event.preventDefault();
    if (!file || !title.trim()) return;
    setBusy(true);
    setStatus("");
    setOverQuota(false);
    try {
      const token = await getApiToken();
      const info = await mediaInfo(file);
      const done = await uploadFile(file, { options: { token }, onProgress: setProgress, seconds: info.seconds });
      const result = await completeUpload({ key: done.key, upload_id: done.upload_id, parts: done.done, title: title.trim(),
        kind: file.type.startsWith("audio/") ? "audio" : "episode", seconds: info.seconds, short_side: info.shortSide,
        size_bytes: file.size }, { token });
      forgetUpload(file);
      const packaging = result.job.lane === "box1" ? "Packaging now." : "Packaging starts when a long-form encoder is free.";
      setStatus(`Uploaded. ${packaging} We check every upload before it can be published.`);
      onDone?.();
    } catch (err) {
      setOverQuota(err instanceof ApiError && err.status === 402);
      setStatus(friendlyErrorMessage(err, "The upload stopped. Pick the same file again to resume."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onUpload} className="space-y-2 rounded-xl border border-border p-3">
      <label className="block text-sm">
        Video or audio file
        <input className="mt-1 block" type="file" accept="video/*,audio/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <label className="block text-sm">
        Title
        <input className="mt-1 w-full rounded border border-border bg-background px-2 py-1" value={title} maxLength={120}
          onChange={(e) => setTitle(e.target.value)} />
      </label>
      <Button type="submit" disabled={busy || !file || !title.trim()}>Upload</Button>
      {busy ? <progress className="block w-full" max={1} value={progress} aria-label="Upload progress" /> : null}
      {status ? <p aria-live="polite" className="text-sm">{status}</p> : null}
      {overQuota ? <a className="text-sm underline" href="/pricing">See plans with more room</a> : null}
    </form>
  );
}
