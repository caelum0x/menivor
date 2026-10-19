"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2, Send, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { listJobs } from "@/lib/api";
import { JobState, type Job } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import {
  isFutureDatetime,
  localDatetimeToUtcISO,
  minScheduleValue,
} from "@/components/schedule/platforms";
import { TonePreview } from "@/components/calendar/TonePreview";
import { LaunchGateNotice, type FeatureGate } from "@/src/shared/launch-gate";
import {
  TONES,
  createChannelPosts,
  errorMessage,
  getChannels,
  problemsOf,
  type Channel,
  type Tone,
} from "@/components/calendar/board-api";

function parseTags(raw: string): string[] {
  return Array.from(
    new Set(
      raw
        .split(/[\s,]+/)
        .map((t) => t.replace(/^#/, "").trim())
        .filter(Boolean),
    ),
  ).slice(0, 30);
}

const OPEN_PUBLISH_GATE: FeatureGate = { open: true, reason: "" };

/**
 * Compose one post for Telegram / Discord / Mastodon channels: text (in a
 * chosen tone), optional hashtags, an optional finished reel attached as the
 * video, and post now or at a time. Shows the exact per-platform text before
 * anything is sent. Calls `onPosted` so the calendar reloads.
 */
export function ChannelComposer({
  open,
  onClose,
  onPosted,
  publishGate = OPEN_PUBLISH_GATE,
}: Readonly<{
  open: boolean;
  onClose: () => void;
  onPosted: (count: number) => void;
  /** Launch gate for posting; while closed the composer explains why and cannot submit. */
  publishGate?: FeatureGate;
}>) {
  const getApiToken = useApiToken();
  const titleId = React.useId();
  const [channels, setChannels] = React.useState<Channel[]>([]);
  const [jobs, setJobs] = React.useState<Job[]>([]);
  const [loadState, setLoadState] = React.useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = React.useState("");
  const [selected, setSelected] = React.useState<string[]>([]);
  const [caption, setCaption] = React.useState("");
  const [tagsRaw, setTagsRaw] = React.useState("");
  const [tone, setTone] = React.useState<Tone>("as_written");
  const [jobId, setJobId] = React.useState("");
  const [when, setWhen] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState("");
  const [problems, setProblems] = React.useState<{ channel_id?: string; message: string }[]>([]);

  React.useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadState("loading");
    (async () => {
      try {
        const token = await getApiToken();
        const [overview, jobList] = await Promise.all([
          getChannels({ token }),
          listJobs({ token }).catch(() => [] as Job[]),
        ]);
        if (cancelled) return;
        const postable = overview.channels.filter((c) => c.can_post);
        setChannels(postable);
        setSelected((prev) => prev.filter((id) => postable.some((c) => c.id === id)));
        setJobs(jobList.filter((j) => j.state === JobState.Complete).slice(0, 30));
        setLoadState("ready");
      } catch (err) {
        if (cancelled) return;
        setLoadError(errorMessage(err, "Couldn't load your channels."));
        setLoadState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, getApiToken]);

  if (!open) return null;

  const hashtags = parseTags(tagsRaw);
  const kinds = Array.from(
    new Set(channels.filter((c) => selected.includes(c.id)).map((c) => c.kind)),
  );
  const scheduleISO = when ? localDatetimeToUtcISO(when) : null;
  const whenOk = !when || isFutureDatetime(when);
  const hasContent = caption.trim().length > 0 || jobId !== "";
  const canSubmit =
    publishGate.open && selected.length > 0 && hasContent && whenOk && !submitting;

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const submit = async () => {
    setSubmitting(true);
    setError("");
    setProblems([]);
    try {
      const token = await getApiToken();
      const result = await createChannelPosts(
        {
          drafts: selected.map((id) => ({ channel_id: id, caption, hashtags })),
          job_id: jobId || undefined,
          scheduled_at: scheduleISO,
          tone,
        },
        { token },
      );
      onPosted(result.posts.length);
      setCaption("");
      setTagsRaw("");
      setJobId("");
      setWhen("");
      onClose();
    } catch (err) {
      setError(errorMessage(err, "Couldn't create the post."));
      setProblems(problemsOf(err));
    } finally {
      setSubmitting(false);
    }
  };

  const labelOf = (id?: string) => channels.find((c) => c.id === id)?.label ?? "Channel";

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog"
      aria-modal="true" aria-labelledby={titleId}>
      <button type="button" aria-label="Close dialog" className="absolute inset-0 bg-black/60"
        onClick={() => !submitting && onClose()} />
      <div className="relative z-10 flex max-h-[92dvh] w-full max-w-3xl flex-col overflow-hidden rounded-t-2xl border border-border bg-card shadow-lg sm:rounded-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-border p-5">
          <div>
            <h2 id={titleId} className="text-lg font-semibold">New channel post</h2>
            <p className="text-sm text-muted-foreground">Telegram, Discord and Mastodon. Free APIs, no review.</p>
          </div>
          <Button variant="ghost" size="icon" aria-label="Close" onClick={onClose} disabled={submitting}>
            <X className="size-4" aria-hidden />
          </Button>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
          <LaunchGateNotice
            gate={publishGate}
            meanwhile="You can still write and preview the post here; it cannot be sent yet."
          />
          {loadState === "loading" && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden /> Loading your channels
            </p>
          )}
          {loadState === "error" && <p className="text-sm text-destructive">{loadError}</p>}
          {loadState === "ready" && channels.length === 0 && (
            <div className="rounded-md border border-dashed border-border p-4 text-sm">
              <p className="font-medium">No channels connected yet.</p>
              <p className="mt-1 text-muted-foreground">
                Connect a Telegram channel, Discord webhook or Mastodon account first.
              </p>
              <Button asChild size="sm" className="mt-3">
                <Link href="/calendar/channels">Connect a channel</Link>
              </Button>
            </div>
          )}
          {loadState === "ready" && channels.length > 0 && (
            <>
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium">Post to</legend>
                <div className="flex flex-wrap gap-2">
                  {channels.map((c) => (
                    <label key={c.id} className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-border px-3 py-1.5 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/10">
                      <input type="checkbox" className="accent-[hsl(var(--primary))]" checked={selected.includes(c.id)}
                        onChange={() => toggle(c.id)} />
                      <span>{c.label}</span>
                      <span className="text-xs text-muted-foreground">{c.kind_label}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2 sm:col-span-2">
                  <Label htmlFor="composer-caption">Text</Label>
                  <Textarea id="composer-caption" rows={4} value={caption} maxLength={4000}
                    onChange={(e) => setCaption(e.target.value)} placeholder="What should this post say?" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="composer-tags">Hashtags</Label>
                  <Input id="composer-tags" value={tagsRaw} onChange={(e) => setTagsRaw(e.target.value)}
                    placeholder="puzzle, mobilegame" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="composer-tone">Tone</Label>
                  <Select id="composer-tone" value={tone} onChange={(e) => setTone(e.target.value as Tone)}>
                    {TONES.map((t) => (
                      <option key={t.id} value={t.id}>{t.label}</option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="composer-reel">Attach a finished reel (optional)</Label>
                  <Select id="composer-reel" value={jobId} onChange={(e) => setJobId(e.target.value)}>
                    <option value="">Text only</option>
                    {jobs.map((j) => (
                      <option key={j.job_id} value={j.job_id}>
                        {(j.hook || "Reel").slice(0, 50)} ({j.job_id.slice(0, 8)})
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="composer-when">When</Label>
                  <Input id="composer-when" type="datetime-local" value={when} min={minScheduleValue()}
                    onChange={(e) => setWhen(e.target.value)} />
                  <p className="text-xs text-muted-foreground">Leave empty to post now. Uses your timezone.</p>
                  {!whenOk && <p className="text-xs text-destructive">Choose a time later than now.</p>}
                </div>
              </div>

              <TonePreview caption={caption} hashtags={hashtags} tone={tone} platforms={kinds} />
              {tone !== "as_written" && (
                <p className="text-xs text-muted-foreground">
                  Tones are simple rewrite rules (for example contractions or trimming filler words), applied
                  the same way every time. Review the preview before posting.
                </p>
              )}
            </>
          )}
          {error && (
            <div className="space-y-1 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
              <p className="text-destructive">{error}</p>
              {problems.map((p) => (
                <p key={`${p.channel_id}-${p.message}`} className="text-xs">
                  {labelOf(p.channel_id)}: {p.message}
                </p>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border p-5">
          <Button variant="outline" onClick={onClose} disabled={submitting}>Cancel</Button>
          <Button onClick={() => void submit()} disabled={!canSubmit}>
            {submitting ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
            {when ? "Schedule" : "Post now"}
          </Button>
        </div>
      </div>
    </div>
  );
}
