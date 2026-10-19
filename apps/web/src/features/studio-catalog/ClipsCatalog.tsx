"use client";

import * as React from "react";
import Link from "next/link";
import {
  ChevronDown,
  ChevronRight,
  Film,
  Loader2,
  RefreshCw,
  Scissors,
  Sparkles,
} from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useApiToken } from "@/lib/use-api-token";
import {
  getClippingJobClips,
  listClippingJobs,
  promoteClip,
  type ClippingJob,
  type ClippingJobClip,
  type ReelDraft,
} from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { safeServerText } from "@/src/shared/errors/friendly";

function errText(err: unknown, fallback: string): string {
  if (err instanceof ApiError || err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

type JobState = "complete" | "processing" | "failed" | "other";

function jobPhase(state: string): JobState {
  const s = state.toLowerCase();
  if (s === "complete" || s === "done") return "complete";
  if (s === "failed" || s === "error") return "failed";
  if (s === "processing" || s === "pending" || s === "queued") return "processing";
  return "other";
}

const STATE_VARIANT: Record<
  JobState,
  "success" | "destructive" | "secondary" | "outline"
> = {
  complete: "success",
  failed: "destructive",
  processing: "secondary",
  other: "outline",
};

interface ClipsRowProps {
  jobId: string;
  getToken: () => Promise<string | undefined>;
  onPromotion: (draft: ReelDraft) => void;
}

function ClipsRow({
  jobId,
  getToken,
  onPromotion,
}: ClipsRowProps): React.JSX.Element {
  const [clips, setClips] = React.useState<ClippingJobClip[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [promotingId, setPromotingId] = React.useState("");

  React.useEffect(() => {
    const ctrl = new AbortController();
    void (async () => {
      try {
        const token = await getToken();
        const list = await getClippingJobClips(jobId, {
          token,
          signal: ctrl.signal,
        });
        if (!ctrl.signal.aborted) setClips(list);
      } catch (err) {
        if (!ctrl.signal.aborted)
          setError(errText(err, "Failed to load clips."));
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    })();
    return () => ctrl.abort();
  }, [jobId, getToken]);

  const onPromote = React.useCallback(
    async (clip: ClippingJobClip) => {
      setPromotingId(clip.id);
      setError("");
      try {
        const token = await getToken();
        const res = await promoteClip(clip.id, { token });
        onPromotion(res.reel_draft);
      } catch (err) {
        setError(errText(err, "Failed to promote clip."));
      } finally {
        setPromotingId("");
      }
    },
    [getToken, onPromotion],
  );

  if (loading) {
    return (
      <p className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading
        clips…
      </p>
    );
  }
  if (error) return <p className="py-2 text-sm text-destructive">{error}</p>;
  if (clips.length === 0) {
    return (
      <p className="py-2 text-sm text-muted-foreground">
        No clips produced yet.
      </p>
    );
  }

  return (
    <div className="mt-3 space-y-2 border-t pt-3">
      {clips.map((clip) => {
        const title = clip.title || clip.hook || `Clip ${clip.id.split(":")[1] ?? clip.id}`;
        const len = clip.length_s ?? (clip.end_s ?? 0) - (clip.start_s ?? 0);
        return (
          <div
            key={clip.id}
            className="flex flex-wrap items-start justify-between gap-3 rounded-md bg-muted/40 px-3 py-2"
          >
            <div className="flex-1 space-y-1">
              <p className="text-sm font-medium leading-tight">{title}</p>
              {len > 0 && (
                <p className="text-xs text-muted-foreground">
                  {len.toFixed(1)}s
                </p>
              )}
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={promotingId === clip.id}
              onClick={() => void onPromote(clip)}
            >
              {promotingId === clip.id ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Film className="mr-1 h-4 w-4" aria-hidden />
              )}
              Promote to reel
            </Button>
          </div>
        );
      })}
    </div>
  );
}

interface JobCardProps {
  job: ClippingJob;
  getToken: () => Promise<string | undefined>;
  onPromotion: (draft: ReelDraft) => void;
}

function JobCard({
  job,
  getToken,
  onPromotion,
}: JobCardProps): React.JSX.Element {
  const phase = jobPhase(job.state);
  const [expanded, setExpanded] = React.useState(false);

  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <div className="flex items-start justify-between gap-2">
          <span className="truncate font-mono text-xs text-muted-foreground">
            {job.id}
          </span>
          <Badge variant={STATE_VARIANT[phase]}>{job.state}</Badge>
        </div>

        {phase === "processing" && job.progress > 0 && (
          <Progress value={job.progress} aria-label="Clipping progress" />
        )}
        {phase === "failed" && job.error && (
          <p className="text-sm text-destructive">{safeServerText(job.error, "This clip could not be made.")}</p>
        )}

        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          {job.language !== "auto" && job.language && (
            <span>Language: {job.language}</span>
          )}
          {job.clip_count > 0 && (
            <span>{job.clip_count} clip{job.clip_count !== 1 ? "s" : ""}</span>
          )}
        </div>

        {phase === "complete" && job.clip_count > 0 && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? (
              <ChevronDown className="mr-1 h-4 w-4" aria-hidden />
            ) : (
              <ChevronRight className="mr-1 h-4 w-4" aria-hidden />
            )}
            {expanded ? "Hide clips" : "View clips"}
          </Button>
        )}

        {expanded && (
          <ClipsRow
            jobId={job.id}
            getToken={getToken}
            onPromotion={onPromotion}
          />
        )}
      </CardContent>
    </Card>
  );
}

interface PromotedDraftBannerProps {
  draft: ReelDraft;
  onDismiss: () => void;
}

function PromotedDraftBanner({
  draft,
  onDismiss,
}: PromotedDraftBannerProps): React.JSX.Element {
  const params = new URLSearchParams({
    subject: draft.video_subject,
    source_kind: draft.source_kind,
    source_ref: draft.source_ref,
    start_s: String(draft.start_s),
    end_s: String(draft.end_s),
  });
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-primary/30 bg-primary/5 p-4">
      <div className="space-y-0.5">
        <p className="text-sm font-medium">Clip promoted to reel draft</p>
        <p className="text-xs text-muted-foreground">{draft.video_subject}</p>
      </div>
      <div className="flex gap-2">
        <Button asChild size="sm">
          <Link href={`/new?${params.toString()}`}>
            <Sparkles className="mr-1 h-4 w-4" aria-hidden /> Open draft
          </Link>
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDismiss}>
          Dismiss
        </Button>
      </div>
    </div>
  );
}

/**
 * Clipping jobs library — lists the caller's long-to-short clipping jobs from
 * GET /clipping/jobs, lets them expand a completed job to browse its clips, and
 * promotes a chosen clip into a new reel draft via POST /clipping/clips/{id}/promote.
 * All wired to the real clipping domain; no fabricated data.
 */
export function ClipsCatalog(): React.JSX.Element {
  const getApiToken = useApiToken();
  const [jobs, setJobs] = React.useState<ClippingJob[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [refreshing, setRefreshing] = React.useState(false);
  const [promotedDraft, setPromotedDraft] = React.useState<ReelDraft | null>(
    null,
  );

  const load = React.useCallback(
    async (signal?: AbortSignal) => {
      setError("");
      const token = await getApiToken();
      try {
        const list = await listClippingJobs({}, { token, signal });
        if (!signal?.aborted) setJobs(list);
      } catch (err) {
        if (!signal?.aborted) setError(errText(err, "Failed to load jobs."));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [getApiToken],
  );

  React.useEffect(() => {
    const ctrl = new AbortController();
    void load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  const onRefresh = React.useCallback(async () => {
    setRefreshing(true);
    setLoading(true);
    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Scissors className="h-5 w-5 text-primary" aria-hidden />
          <span className="font-medium">
            Clipping jobs
            {jobs.length > 0 && (
              <span className="ml-1 text-muted-foreground">({jobs.length})</span>
            )}
          </span>
        </div>
        <div className="flex gap-2">
          <Button asChild size="sm" variant="outline">
            <Link href="/new">
              <Sparkles className="mr-1 h-4 w-4" aria-hidden /> New job
            </Link>
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => void onRefresh()}
            disabled={refreshing || loading}
          >
            <RefreshCw
              className={`mr-1 h-4 w-4 ${refreshing ? "animate-spin" : ""}`}
              aria-hidden
            />
            Refresh
          </Button>
        </div>
      </div>

      {promotedDraft && (
        <PromotedDraftBanner
          draft={promotedDraft}
          onDismiss={() => setPromotedDraft(null)}
        />
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}

      {loading ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading
          jobs…
        </p>
      ) : jobs.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center">
          <Scissors
            className="mx-auto mb-2 h-8 w-8 text-muted-foreground"
            aria-hidden
          />
          <p className="mb-4 text-sm text-muted-foreground">
            No clipping jobs yet. Start one from a long recording or URL.
          </p>
          <Button asChild size="sm">
            <Link href="/new">
              <Sparkles className="mr-1 h-4 w-4" aria-hidden /> Create clipping
              job
            </Link>
          </Button>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {jobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              getToken={getApiToken}
              onPromotion={setPromotedDraft}
            />
          ))}
        </div>
      )}
    </div>
  );
}
