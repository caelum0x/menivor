"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { CalendarClock, Loader2, Send, Share2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  listNativePlatforms,
  publishNative,
  type NativePublishResult,
} from "./api";
import { schedulePost } from "@/src/features/channel-console/api";
import { ReelPicker } from "@/src/features/reels-library/components/ReelPicker";
import { LaunchGateNotice, readableApiError, useLaunchGate } from "@/src/shared/launch-gate";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface NativePublishForm {
  jobId: string;
  platform: string;
  title: string;
  caption: string;
  hashtags: string;
  publishAt: string;
}

export type NativePublishCommand =
  | {
      kind: "publish";
      jobId: string;
      body: Parameters<typeof publishNative>[1];
    }
  | {
      kind: "schedule";
      jobId: string;
      body: Parameters<typeof schedulePost>[1];
    };

/** Normalize and validate the exact mutation before authentication/network I/O. */
export function buildNativePublishCommand(
  form: NativePublishForm,
  nowMs = Date.now(),
): NativePublishCommand {
  const jobId = form.jobId.trim();
  const platform = form.platform.trim();
  if (!jobId) throw new Error("Job ID is required.");
  if (!platform) throw new Error("Choose a publishing platform.");
  if (form.publishAt.trim()) {
    const scheduledMs = Date.parse(form.publishAt);
    if (!Number.isFinite(scheduledMs)) throw new Error("Choose a valid schedule time.");
    if (scheduledMs <= nowMs) throw new Error("Schedule time must be in the future.");
    return {
      kind: "schedule",
      jobId,
      body: { platforms: [platform], scheduled_at: new Date(scheduledMs).toISOString() },
    };
  }
  const title = form.title.trim();
  const caption = form.caption.trim();
  if (title.length > 200) throw new Error("Title must be at most 200 characters.");
  if (caption.length > 2200) throw new Error("Caption must be at most 2,200 characters.");
  const hashtags = Array.from(
    new Set(form.hashtags.split(",").map((tag) => tag.trim()).filter(Boolean)),
  );
  if (hashtags.length > 30) throw new Error("Use at most 30 hashtags.");
  return {
    kind: "publish",
    jobId,
    body: {
      platform,
      title: title || undefined,
      caption: caption || undefined,
      hashtags: hashtags.length > 0 ? hashtags : undefined,
    },
  };
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `publish-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export interface NativePublishProps {
  /** Reel to preselect, e.g. from `/publish?job=<id>` on the reel page. */
  initialJobId?: string;
}

/** Publish a rendered job natively to a chosen platform. */
export function NativePublish({ initialJobId = "" }: Readonly<NativePublishProps> = {}) {
  const { getToken } = useAuth();
  const launch = useLaunchGate();
  const publishGate = launch.gate.publishing;
  const [platforms, setPlatforms] = React.useState<string[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [jobId, setJobId] = React.useState(initialJobId.trim());
  const [platform, setPlatform] = React.useState("");
  const [title, setTitle] = React.useState("");
  const [caption, setCaption] = React.useState("");
  const [hashtags, setHashtags] = React.useState("");
  const [publishAt, setPublishAt] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<NativePublishResult | null>(null);
  const [scheduledMsg, setScheduledMsg] = React.useState("");
  const inFlight = React.useRef(false);
  const pending = React.useRef<{ signature: string; idempotencyKey: string } | null>(null);

  const load = React.useCallback(async () => {
    try {
      const token = (await getToken()) ?? undefined;
      const res = await listNativePlatforms({ token });
      setPlatforms(res.platforms);
      setPlatform((current) =>
        res.platforms.includes(current) ? current : (res.platforms[0] ?? ""),
      );
    } catch (err) {
      setError(readableApiError(err, "Failed to load platforms."));
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const onPublish = React.useCallback(async () => {
    if (inFlight.current || !publishGate.open) return;
    let command: NativePublishCommand;
    try {
      command = buildNativePublishCommand({ jobId, platform, title, caption, hashtags, publishAt });
    } catch (err) {
      setError(friendlyErrorMessage(err, "Invalid publishing command."));
      return;
    }
    const signature = JSON.stringify(command);
    if (!pending.current || pending.current.signature !== signature) {
      pending.current = { signature, idempotencyKey: newIdempotencyKey() };
    }
    const commandKey = pending.current.idempotencyKey;
    inFlight.current = true;
    setBusy(true);
    setError("");
    setResult(null);
    setScheduledMsg("");
    try {
      const token = (await getToken()) ?? undefined;
      if (command.kind === "schedule") {
        const scheduled = await schedulePost(
          command.jobId,
          command.body,
          { token, idempotencyKey: commandKey },
        );
        pending.current = null;
        setScheduledMsg(
          `Queued for ${command.body.platforms[0]} · status ${scheduled.status}. Track it in the channel console.`,
        );
        return;
      }
      const res = await publishNative(
        command.jobId,
        command.body,
        { token, idempotencyKey: commandKey },
      );
      pending.current = null;
      setResult(res);
    } catch (err) {
      setError(readableApiError(err, "Failed to publish."));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }, [jobId, platform, title, caption, hashtags, publishAt, getToken, publishGate.open]);

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="space-y-4 py-5">
          <div className="flex items-center gap-2">
            <Share2 className="h-4 w-4 text-primary" aria-hidden />
            <h2 className="font-semibold">Publish to platform</h2>
          </div>

          <LaunchGateNotice
            gate={publishGate}
            meanwhile="You can still pick a reel and download it from its page to post by hand."
          />

          <div className="space-y-2">
            <p className="text-sm font-medium">Choose a finished reel</p>
            <ReelPicker
              selectedId={jobId.trim()}
              onSelect={(id) => setJobId(id)}
              limit={8}
              emptyLabel="You have no finished reels to publish yet."
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="np-job">Job ID</Label>
            <Input
              id="np-job"
              placeholder="Selected above, or paste a reel id"
              value={jobId}
              onChange={(e) => setJobId(e.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="np-platform">Platform</Label>
            <Select
              id="np-platform"
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              disabled={loading || platforms.length === 0}
            >
              {platforms.length === 0 ? (
                <option value="">No platforms available</option>
              ) : (
                platforms.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))
              )}
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="np-title">Title</Label>
            <Input
              id="np-title"
              placeholder="Optional title"
              value={title}
              maxLength={200}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="np-caption">Caption</Label>
            <Textarea
              id="np-caption"
              placeholder="Optional caption"
              value={caption}
              maxLength={2200}
              onChange={(e) => setCaption(e.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="np-hashtags">Hashtags (comma-separated)</Label>
            <Input
              id="np-hashtags"
              placeholder="viral, fyp, reels"
              value={hashtags}
              onChange={(e) => setHashtags(e.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="np-when">Schedule for later (optional)</Label>
            <Input
              id="np-when"
              type="datetime-local"
              value={publishAt}
              onChange={(e) => setPublishAt(e.target.value)}
            />
          </div>

          {publishAt.trim() && (
            <p className="text-xs text-muted-foreground">
              Scheduled publishing uses the rendered job and platform defaults.
              Title, caption, and hashtags above apply only to immediate publishing.
            </p>
          )}

          <Button
            onClick={() => void onPublish()}
            disabled={busy || loading || !publishGate.open || !jobId.trim() || !platform}
          >
            {busy ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
            ) : publishAt.trim() ? (
              <CalendarClock className="mr-1 h-4 w-4" aria-hidden />
            ) : (
              <Send className="mr-1 h-4 w-4" aria-hidden />
            )}
            {publishAt.trim() ? "Schedule" : "Publish"}
          </Button>

          {scheduledMsg && <p className="text-sm text-success">{scheduledMsg}</p>}

          {result && (
            <div className="rounded-md border border-primary/40 bg-primary/5 p-3 text-sm">
              <div className="mb-1 flex items-center gap-2">
                <span className="font-medium text-primary">{result.platform}</span>
                <Badge variant="secondary">{result.status}</Badge>
              </div>
              {result.url && (
                <a
                  href={result.url}
                  target="_blank"
                  rel="noreferrer"
                  className="break-all text-xs text-primary underline"
                >
                  {result.url}
                </a>
              )}
            </div>
          )}
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>
    </div>
  );
}
