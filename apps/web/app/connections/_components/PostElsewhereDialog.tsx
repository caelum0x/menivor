"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Loader2, Pencil, Send, X } from "lucide-react";
import type { Job } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { RequestOptions } from "@/src/shared/api";
import {
  checkFormats,
  createPosts,
  errorText,
  problemsOf,
  type ExtendedPlatform,
  type FittedPost,
  type PlatformPost,
  type PlatformRecord,
  type PostDraft,
  type Problem,
} from "../_lib/publishing-api";
import { PLATFORM_ICONS, POST_STATUS_LABELS, formatWhen } from "./platform-meta";

export interface PostElsewhereDialogProps {
  open: boolean;
  onClose: () => void;
  /** Connected, ready extended platforms. */
  platforms: readonly PlatformRecord[];
  jobs: readonly Job[];
  getOptions: () => Promise<RequestOptions>;
}

const PREVIEW_DELAY_MS = 400;

function jobLabel(job: Job): string {
  const hook = job.hook?.trim();
  if (hook) return hook.length > 60 ? `${hook.slice(0, 57)}...` : hook;
  return `Reel ${job.job_id.slice(0, 8)}`;
}

function parseTags(raw: string): string[] {
  return raw
    .split(/[\s,]+/)
    .map((t) => t.replace(/^#/, "").trim())
    .filter(Boolean)
    .slice(0, 30);
}

function localInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Post one finished reel to several extended platforms, now or at a set time. */
export function PostElsewhereDialog({ open, onClose, platforms, jobs, getOptions }: Readonly<PostElsewhereDialogProps>) {
  const titleId = React.useId();
  const reelId = React.useId();
  const captionId = React.useId();
  const postTitleId = React.useId();
  const tagsId = React.useId();
  const whenId = React.useId();

  const [jobId, setJobId] = React.useState("");
  const [selected, setSelected] = React.useState<ReadonlySet<ExtendedPlatform>>(new Set());
  const [caption, setCaption] = React.useState("");
  const [title, setTitle] = React.useState("");
  const [tags, setTags] = React.useState("");
  const [overrides, setOverrides] = React.useState<Readonly<Partial<Record<ExtendedPlatform, string>>>>({});
  const [editing, setEditing] = React.useState<ExtendedPlatform | null>(null);
  const [later, setLater] = React.useState(false);
  const [when, setWhen] = React.useState("");
  const [preview, setPreview] = React.useState<readonly FittedPost[]>([]);
  const [previewError, setPreviewError] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [submitError, setSubmitError] = React.useState("");
  const [problems, setProblems] = React.useState<readonly Problem[]>([]);
  const [created, setCreated] = React.useState<readonly PlatformPost[] | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setJobId(jobs[0]?.job_id ?? "");
    setSelected(new Set(platforms.map((p) => p.platform)));
    setCaption("");
    setTitle("");
    setTags("");
    setOverrides({});
    setEditing(null);
    setLater(false);
    setWhen(localInputValue(new Date(Date.now() + 60 * 60 * 1000)));
    setPreview([]);
    setSubmitError("");
    setProblems([]);
    setCreated(null);
  }, [open, jobs, platforms]);

  const drafts = React.useMemo<PostDraft[]>(() => {
    const hashtags = parseTags(tags);
    return platforms
      .filter((p) => selected.has(p.platform))
      .map((p) => ({ platform: p.platform, caption: overrides[p.platform] ?? caption, title, hashtags }));
  }, [platforms, selected, overrides, caption, title, tags]);

  React.useEffect(() => {
    if (!open || drafts.length === 0) {
      setPreview([]);
      return;
    }
    const handle = window.setTimeout(async () => {
      try {
        const { results } = await checkFormats(drafts, await getOptions());
        setPreview(results);
        setPreviewError("");
      } catch (err) {
        setPreviewError(errorText(err, "Couldn't check the caption limits."));
      }
    }, PREVIEW_DELAY_MS);
    return () => window.clearTimeout(handle);
  }, [open, drafts, getOptions]);

  const requestClose = React.useCallback(() => {
    if (!submitting) onClose();
  }, [submitting, onClose]);

  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") requestClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, requestClose]);

  const toggle = (platform: ExtendedPlatform) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(platform)) next.delete(platform);
      else next.add(platform);
      return next;
    });

  const scheduledIso = later && when ? new Date(when).toISOString() : null;
  const laterInvalid = later && (!when || new Date(when).getTime() < Date.now() - 60_000);
  const blocking = preview.some((p) => !p.ok);
  const canSubmit = Boolean(jobId) && drafts.length > 0 && !submitting && !laterInvalid && !blocking;

  const submit = async () => {
    setSubmitting(true);
    setSubmitError("");
    setProblems([]);
    try {
      const { posts } = await createPosts(jobId, drafts, scheduledIso, await getOptions());
      setCreated(posts);
    } catch (err) {
      setProblems(problemsOf(err));
      setSubmitError(errorText(err, "Couldn't queue this post."));
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true"
      aria-labelledby={titleId}>
      <button type="button" aria-label="Close dialog" className="absolute inset-0 bg-black/60" onClick={requestClose} />
      <div className="relative z-10 flex max-h-[92dvh] w-full max-w-2xl flex-col overflow-hidden rounded-t-2xl border border-border bg-card shadow-lg sm:rounded-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-border p-5">
          <div className="space-y-1">
            <h2 id={titleId} className="flex items-center gap-2 text-lg font-semibold">
              <Send className="size-5 text-primary" aria-hidden />
              Post to more platforms
            </h2>
            <p className="text-sm text-muted-foreground">
              One caption, fitted to each platform. Post now or pick a time.
            </p>
          </div>
          <Button variant="ghost" size="icon" aria-label="Close" onClick={requestClose} disabled={submitting}>
            <X className="size-4" aria-hidden />
          </Button>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
          {created ? (
            <div className="space-y-3">
              <p className="flex items-center gap-2 font-medium">
                <CheckCircle2 className="size-5 text-success" aria-hidden />
                {scheduledIso ? `Scheduled for ${formatWhen(scheduledIso)}` : "Posting now"}
              </p>
              <ul className="space-y-1 text-sm">
                {created.map((p) => (
                  <li key={p.id} className="flex justify-between gap-2">
                    <span>{p.platform_label}</span>
                    <span className="text-muted-foreground">{POST_STATUS_LABELS[p.status]}</span>
                  </li>
                ))}
              </ul>
              <p className="text-sm text-muted-foreground">
                Follow progress in the{" "}
                <Link href="/connections/queue" className="text-primary underline-offset-4 hover:underline">
                  queue
                </Link>
                . Some platforms take a few minutes to process video.
              </p>
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <Label htmlFor={reelId}>Reel</Label>
                <Select id={reelId} value={jobId} disabled={submitting} onChange={(e) => setJobId(e.target.value)}>
                  {jobs.map((job) => (
                    <option key={job.job_id} value={job.job_id}>
                      {jobLabel(job)}
                    </option>
                  ))}
                </Select>
              </div>

              <fieldset className="space-y-2">
                <legend className="text-sm font-medium">Platforms</legend>
                <div className="flex flex-wrap gap-2">
                  {platforms.map((p) => {
                    const Icon = PLATFORM_ICONS[p.platform];
                    const on = selected.has(p.platform);
                    return (
                      <button
                        key={p.platform}
                        type="button"
                        aria-pressed={on}
                        onClick={() => toggle(p.platform)}
                        disabled={submitting}
                        className={
                          on
                            ? "inline-flex items-center gap-1.5 rounded-full border border-primary bg-primary/10 px-3 py-1.5 text-sm"
                            : "inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1.5 text-sm text-muted-foreground"
                        }
                      >
                        <Icon className="size-4" aria-hidden />
                        {p.label}
                      </button>
                    );
                  })}
                </div>
              </fieldset>

              <div className="space-y-2">
                <Label htmlFor={captionId}>Caption</Label>
                <Textarea id={captionId} rows={4} maxLength={6000} value={caption} disabled={submitting}
                  placeholder="What should people know about this reel?" onChange={(e) => setCaption(e.target.value)} />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor={postTitleId}>Title (Facebook, LinkedIn, Pinterest)</Label>
                  <Input id={postTitleId} maxLength={300} value={title} disabled={submitting}
                    onChange={(e) => setTitle(e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor={tagsId}>Hashtags</Label>
                  <Input id={tagsId} value={tags} disabled={submitting} placeholder="smallbusiness, launch"
                    onChange={(e) => setTags(e.target.value)} />
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-sm font-medium">When</p>
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <label className="inline-flex items-center gap-2">
                    <input type="radio" name="when" checked={!later} onChange={() => setLater(false)} disabled={submitting} />
                    Now
                  </label>
                  <label className="inline-flex items-center gap-2">
                    <input type="radio" name="when" checked={later} onChange={() => setLater(true)} disabled={submitting} />
                    Later
                  </label>
                  {later && (
                    <div className="min-w-[14rem]">
                      <label htmlFor={whenId} className="sr-only">Post at</label>
                      <Input id={whenId} type="datetime-local" value={when} disabled={submitting}
                        onChange={(e) => setWhen(e.target.value)} />
                    </div>
                  )}
                </div>
                {laterInvalid && <p className="text-xs text-destructive">Pick a time in the future.</p>}
              </div>

              {drafts.length > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium">What each platform gets</p>
                  {previewError && <p className="text-xs text-destructive">{previewError}</p>}
                  <ul className="space-y-2">
                    {preview.map((fitted) => {
                      const Icon = PLATFORM_ICONS[fitted.platform];
                      const label = platforms.find((p) => p.platform === fitted.platform)?.label ?? fitted.platform;
                      const over = fitted.length > fitted.limit;
                      return (
                        <li key={fitted.platform} className="rounded-lg border border-border p-3">
                          <div className="flex items-center justify-between gap-2 text-sm">
                            <span className="flex items-center gap-1.5 font-medium">
                              <Icon className="size-4" aria-hidden /> {label}
                            </span>
                            <span className={over ? "text-xs text-destructive" : "text-xs text-muted-foreground"}>
                              {fitted.length}/{fitted.limit}
                            </span>
                          </div>
                          {editing === fitted.platform ? (
                            <Textarea className="mt-2" rows={3} value={overrides[fitted.platform] ?? caption}
                              onChange={(e) => setOverrides((prev) => ({ ...prev, [fitted.platform]: e.target.value }))} />
                          ) : (
                            <p className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">
                              {fitted.text || "No caption"}
                            </p>
                          )}
                          {fitted.issues.map((issue) => (
                            <p key={issue.message}
                              className={issue.level === "error" ? "mt-1 text-xs text-destructive" : "mt-1 text-xs text-muted-foreground"}>
                              {issue.message}
                            </p>
                          ))}
                          <button type="button"
                            className="mt-2 inline-flex items-center gap-1 text-xs text-primary underline-offset-4 hover:underline"
                            onClick={() => setEditing(editing === fitted.platform ? null : fitted.platform)}>
                            <Pencil className="size-3" aria-hidden />
                            {editing === fitted.platform ? "Done" : "Edit for this platform"}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}

              {submitError && (
                <div className="space-y-1 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm" role="alert">
                  <p className="flex items-center gap-2 font-medium">
                    <AlertTriangle className="size-4 text-destructive" aria-hidden /> {submitError}
                  </p>
                  {problems.map((p) => (
                    <p key={p.platform} className="text-muted-foreground">
                      {platforms.find((x) => x.platform === p.platform)?.label ?? p.platform}: {p.message}
                    </p>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-border p-4">
          <Button variant="outline" onClick={requestClose} disabled={submitting}>
            {created ? "Close" : "Cancel"}
          </Button>
          {!created && (
            <Button onClick={() => void submit()} disabled={!canSubmit}>
              {submitting ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
              {later ? "Schedule" : "Post now"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
