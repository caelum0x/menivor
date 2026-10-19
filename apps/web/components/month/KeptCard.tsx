"use client";

import * as React from "react";
import Link from "next/link";
import { Check, Copy, Download, FileText, Film, Loader2, Pencil, RotateCcw, Sparkles, Undo2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { ErrorText, errorMessage } from "@/components/design/shared";

import { decideIdea, editIdea, makeReel, renderCarousel, retryVideo } from "./api";
import { IdeaPreview } from "./SwipeDeck";
import type { IdeaUpdate, MonthIdea, SlideSize } from "./types";

type Options = () => Promise<{ token?: string }>;

function VideoState({ idea, onRetry, busy }: { idea: MonthIdea; onRetry: () => void; busy: boolean }) {
  const status = idea.outputs.video_status;
  if (status === "queued" || status === "rendering") {
    return (
      <p className="flex items-center gap-2 text-xs text-muted-foreground" aria-live="polite">
        <Loader2 className="size-3.5 animate-spin" aria-hidden /> Making the video…
      </p>
    );
  }
  if (status === "failed") {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>{idea.outputs.video_error || "The video could not be made."}</span>
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onRetry}>
          <RotateCcw aria-hidden /> Try again
        </Button>
      </div>
    );
  }
  return null;
}

function Downloads({ idea, onRetry, busy }: { idea: MonthIdea; onRetry: () => void; busy: boolean }) {
  const out = idea.outputs;
  const pngs = out.png_urls.filter((u): u is string => Boolean(u));
  return (
    <div className="space-y-3">
      <div className="flex gap-2 overflow-x-auto pb-1">
        {pngs.map((url, i) => (
          <a key={url} href={url} target="_blank" rel="noreferrer" className="shrink-0" aria-label={`Slide ${i + 1}`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={url} alt={`Slide ${i + 1}`} className="h-28 w-auto rounded-md ring-1 ring-white/10" />
          </a>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {out.mp4_url ? (
          <Button asChild size="sm">
            <a href={out.mp4_url} download>
              <Film aria-hidden /> Video
            </a>
          </Button>
        ) : null}
        {out.pdf_url ? (
          <Button asChild size="sm" variant="outline">
            <a href={out.pdf_url} download>
              <FileText aria-hidden /> PDF
            </a>
          </Button>
        ) : null}
        {pngs.length ? (
          <Button asChild size="sm" variant="outline">
            <a href={pngs[0]} download>
              <Download aria-hidden /> Slides
            </a>
          </Button>
        ) : null}
      </div>
      <VideoState idea={idea} onRetry={onRetry} busy={busy} />
      {out.error ? <p className="text-xs text-muted-foreground">{out.error}</p> : null}
    </div>
  );
}

function CopyCaption({ caption }: { caption: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <Button
      type="button"
      size="icon"
      variant="ghost"
      aria-label="Copy caption"
      title="Copy caption"
      onClick={() => {
        void navigator.clipboard?.writeText(caption).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      {copied ? <Check className="text-emerald-500" aria-hidden /> : <Copy aria-hidden />}
    </Button>
  );
}

/** One kept post: make it (slides or reel), download it, copy the caption, edit the text. */
export function KeptCard({
  idea,
  size,
  getOptions,
  onUpdate,
  busy,
  setBusy,
}: {
  idea: MonthIdea;
  size: SlideSize;
  getOptions: Options;
  onUpdate: (u: IdeaUpdate) => void;
  busy: boolean;
  setBusy: (id: string | null) => void;
}) {
  const [error, setError] = React.useState("");
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(idea.slides.join("\n"));

  const run = async (work: () => Promise<IdeaUpdate>) => {
    setBusy(idea.id);
    setError("");
    try {
      onUpdate(await work());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const make = () =>
    run(async () => {
      const opts = await getOptions();
      return idea.kind === "reel" ? makeReel(idea, opts) : renderCarousel(idea.id, size, opts);
    });

  const save = () =>
    run(async () => {
      const lines = draft.split("\n").map((l) => l.trim()).filter(Boolean);
      const update = await editIdea(idea.id, { slides: lines }, await getOptions());
      setEditing(false);
      return update;
    });

  const made = idea.render_status === "done" || idea.render_status === "queued";
  return (
    <Card className="overflow-hidden">
      <CardContent className="flex gap-4 p-4">
        <div className="hidden shrink-0 sm:block">
          <IdeaPreview idea={idea} getOptions={getOptions} maxW={120} maxH={200} />
        </div>
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="text-xs text-muted-foreground">
                {idea.kind === "reel" ? "Reel" : "Carousel"} · {idea.format_name}
              </p>
              <p className="font-semibold leading-snug">{idea.hook}</p>
            </div>
            <div className="flex shrink-0">
              <CopyCaption caption={idea.caption} />
              <Button type="button" size="icon" variant="ghost" aria-label="Edit text" title="Edit text"
                      onClick={() => setEditing((v) => !v)}>
                <Pencil aria-hidden />
              </Button>
              <Button type="button" size="icon" variant="ghost" aria-label="Move back to the deck" title="Undo keep"
                      disabled={busy} onClick={() => run(async () => decideIdea(idea.id, "pending", await getOptions()))}>
                <Undo2 aria-hidden />
              </Button>
            </div>
          </div>
          {editing ? (
            <div className="space-y-2">
              <Textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={Math.min(8, idea.slides.length + 1)}
                        aria-label="One slide per line" />
              <Button type="button" size="sm" disabled={busy} onClick={save}>Save</Button>
            </div>
          ) : null}
          {idea.render_status === "done" ? (
            <Downloads
              idea={idea}
              busy={busy}
              onRetry={() => run(async () => retryVideo(idea.id, await getOptions()))}
            />
          ) : null}
          {idea.render_status === "queued" && idea.outputs.job_id ? (
            <Button asChild size="sm" variant="outline">
              <Link href={`/jobs/${encodeURIComponent(idea.outputs.job_id)}`}>
                <Film aria-hidden /> Open reel
              </Link>
            </Button>
          ) : null}
          {!made ? (
            <Button type="button" size="sm" disabled={busy} onClick={make}>
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />}
              {idea.kind === "reel" ? "Make reel" : "Make slides"}
            </Button>
          ) : null}
          <ErrorText message={error} />
        </div>
      </CardContent>
    </Card>
  );
}
