"use client";

/**
 * Live progress + results for a one-flow run. Polls every variant's
 * `GET /jobs/{id}` until all three are terminal, showing each variant's
 * current pipeline stage. Finished variants play inline and offer pick,
 * edit, publish and download; failed ones show that their credit was
 * refunded and can be retried.
 */

import * as React from "react";
import Link from "next/link";
import {
  AlertCircle,
  Check,
  Clock,
  Download,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Send,
  Star,
} from "lucide-react";
import { ApiError, POLL_INTERVAL_MS, getJob, retryJob } from "@/lib/api";
import { formatLockOf, formatLockedMessage, isCreditShortfall } from "@/src/shared/launch";
import { BuyCredits } from "@/src/shared/access";
import { PlanUpsell } from "@/src/features/plans";
import { PaywallMoment } from "@/src/features/paywall-moment";
import { ShareToX } from "@/src/features/share-x/ShareToX";

/**
 * A retry re-checks the format before any credit is debited, so a 402 is
 * either a locked format (name it) or a real credit shortfall.
 */
export function retryErrorMessage(err: unknown): string {
  const lock = formatLockOf(err);
  if (lock) return formatLockedMessage(lock);
  if (isCreditShortfall(err)) return "Retrying needs 1 credit and your balance is empty.";
  return friendlyErrorMessage(err, "Retry failed.");
}
import type { Job } from "@/lib/types";
import { isTerminalState } from "@/lib/types";
import { jobResultUrl, jobThumbnailUrl } from "@/lib/job-media";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useApiToken } from "@/lib/use-api-token";
import { cn } from "@/lib/utils";
import {
  currentStageLabel,
  renderingEtaLabel,
  hookStyleLabel,
  formatElapsed,
  variantPhase,
  variantProgress,
  type VariantPhase,
} from "./plan";
import { loadPick, loadRun, savePick, type RunMeta } from "./run-store";
import { ResultHero } from "./ResultHero";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { safeServerText } from "@/src/shared/errors/friendly";

export interface VariantResultsProps {
  readonly jobIds: readonly string[];
}

const VARIANT_LETTERS = ["A", "B", "C"] as const;
/** Poll at the normal pace this long, then back off (never give up). */
export const FAST_POLL_WINDOW_MS = 20 * 60 * 1000;
/** Slowest poll once backed off. */
export const MAX_POLL_DELAY_MS = 60 * 1000;
const BACKOFF_FACTOR = 1.5;

/**
 * Delay before the next status poll. The page never stops polling while a
 * reel is unfinished (a render queue can be long): the normal pace for the
 * first 20 minutes, then each wait grows by half up to one minute.
 */
export function nextPollDelay(elapsedMs: number, previousDelayMs: number): number {
  if (elapsedMs < FAST_POLL_WINDOW_MS) return POLL_INTERVAL_MS;
  const grown = Math.round(Math.max(previousDelayMs, POLL_INTERVAL_MS) * BACKOFF_FACTOR);
  return Math.min(MAX_POLL_DELAY_MS, grown);
}

interface VariantState {
  readonly job?: Job;
  readonly error?: string;
}

function angleLabel(meta: RunMeta | null, jobId: string): string {
  return hookStyleLabel(meta?.variants.find((v) => v.jobId === jobId)?.angle);
}

function hookFor(meta: RunMeta | null, jobId: string, job?: Job): string {
  const planned = meta?.variants.find((v) => v.jobId === jobId)?.hook;
  const fromJob = typeof job?.hook === "string" ? job.hook.trim() : "";
  // The API falls back to the subject until the script stage has written the
  // real hook; prefer the planned hook (link mode) in that window.
  return planned || fromJob;
}

const PHASE_BADGE: Record<VariantPhase, { label: string; variant: "secondary" | "default" | "success" | "destructive" }> = {
  queued: { label: "Queued", variant: "secondary" },
  rendering: { label: "Rendering", variant: "default" },
  ready: { label: "Ready", variant: "success" },
  failed: { label: "Failed", variant: "destructive" },
};

export function VariantResults({ jobIds }: VariantResultsProps) {
  const getApiToken = useApiToken();
  const [meta, setMeta] = React.useState<RunMeta | null>(null);
  const [variants, setVariants] = React.useState<Record<string, VariantState>>({});
  const [picked, setPicked] = React.useState("");
  const [now, setNow] = React.useState(() => Date.now());
  const [pollNonce, setPollNonce] = React.useState(0);
  const [slow, setSlow] = React.useState(false);
  const [retrying, setRetrying] = React.useState("");
  const startRef = React.useRef<number>(Date.now());

  const idsKey = jobIds.join(",");

  React.useEffect(() => {
    const run = loadRun(jobIds);
    setMeta(run);
    if (run) startRef.current = run.startedAt;
    setPicked(loadPick(jobIds));
    // jobIds identity changes per render; the joined key is the real dependency.
  }, [idsKey]);

  const allTerminal =
    jobIds.length > 0 &&
    jobIds.every((id) => {
      const job = variants[id]?.job;
      return job ? isTerminalState(job.state) : false;
    });

  // Poll every non-terminal variant until all are done.
  React.useEffect(() => {
    if (jobIds.length === 0) return;
    let active = true;
    const controller = new AbortController();
    const pollStart = Date.now();
    let delay = POLL_INTERVAL_MS;
    setSlow(false);

    const tick = async () => {
      const token = await getApiToken();
      const results = await Promise.all(
        jobIds.map(async (id): Promise<[string, VariantState]> => {
          try {
            const job = await getJob(id, { token, signal: controller.signal });
            return [id, { job }];
          } catch (err) {
            const message =
              err instanceof ApiError && err.status === 404
                ? "This reel wasn't found on your account."
                : friendlyErrorMessage(err, "Could not load this reel.");
            return [id, { error: message }];
          }
        }),
      );
      if (!active) return true;
      setVariants((prev) => {
        const next = { ...prev };
        for (const [id, state] of results) {
          // Keep the last good snapshot through a transient poll error.
          next[id] = state.job ? state : { ...prev[id], error: state.error };
        }
        return next;
      });
      return results.every(([, state]) =>
        state.job ? isTerminalState(state.job.state) : state.error?.includes("wasn't found"),
      );
    };

    void (async () => {
      while (active) {
        let done = false;
        try {
          done = await tick();
        } catch {
          // Token or network hiccup: try again next interval.
        }
        if (done || !active) return;
        const elapsed = Date.now() - pollStart;
        if (elapsed >= FAST_POLL_WINDOW_MS) setSlow(true);
        delay = nextPollDelay(elapsed, delay);
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    })();

    return () => {
      active = false;
      controller.abort();
    };
  }, [idsKey, getApiToken, pollNonce]);

  // Elapsed-time readout while anything is still rendering.
  React.useEffect(() => {
    if (allTerminal) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [allTerminal]);

  const handlePick = (id: string) => {
    setPicked(id);
    savePick(jobIds, id);
  };

  const handleRetry = async (id: string) => {
    setRetrying(id);
    try {
      const token = await getApiToken();
      const job = await retryJob(id, { token });
      setVariants((prev) => ({ ...prev, [id]: { job } }));
      setPollNonce((n) => n + 1);
    } catch (err) {
      setVariants((prev) => ({
        ...prev,
        [id]: {
          ...prev[id],
          error: retryErrorMessage(err),
        },
      }));
    } finally {
      setRetrying("");
    }
  };

  if (jobIds.length === 0) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6">
          <p className="text-sm text-muted-foreground">
            There are no reels to show for this link.
          </p>
          <Button asChild size="sm">
            <Link href="/create">
              <Plus className="size-4" aria-hidden /> Make 3 reels
            </Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  const readyCount = jobIds.filter((id) => variantPhase(variants[id]?.job) === "ready").length;
  // The ticker stops once everything is terminal, freezing the readout.
  const elapsed = formatElapsed(now - startRef.current);
  const pickedJob = picked ? variants[picked]?.job : undefined;
  // The big preview: the creator's pick, else the first finished version.
  const heroJob =
    pickedJob && variantPhase(pickedJob) === "ready"
      ? pickedJob
      : jobIds.map((id) => variants[id]?.job).find((job) => variantPhase(job) === "ready");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
          {allTerminal ? (
            <Check className="size-4 text-primary" aria-hidden />
          ) : (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          )}
          {allTerminal
            ? `${readyCount} of ${jobIds.length} reels ready.`
            : `Rendering ${jobIds.length} reels. ${readyCount} ready so far.`}
          {(meta || !allTerminal) && (
            <span className="inline-flex items-center gap-1">
              <Clock className="size-3.5" aria-hidden /> {elapsed}
            </span>
          )}
        </p>
        {!allTerminal && (
          <p className="text-xs text-muted-foreground">
            You can leave this page. Your reels keep rendering and show up in My reels.
          </p>
        )}
      </div>

      {meta?.notice && (
        <p className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden /> {meta.notice}
        </p>
      )}

      {slow && !allTerminal && (
        <p className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground" role="status">
          This is taking longer than usual. We keep checking, and we email you when your reels
          are ready, so you can close this tab.
          <Button type="button" variant="outline" size="sm" onClick={() => setPollNonce((n) => n + 1)}>
            <RefreshCw className="size-4" aria-hidden /> Check again
          </Button>
        </p>
      )}

      {heroJob && (
        <ResultHero
          job={heroJob}
          letter={VARIANT_LETTERS[jobIds.indexOf(heroJob.job_id)] ?? ""}
          readyInRun={readyCount}
          input={meta?.input}
          hook={hookFor(meta, heroJob.job_id, heroJob)}
          sourceUrl={meta?.source === "link" ? meta.input : heroJob.source_url}
        />
      )}

      {heroJob && (
        <h2 className="pt-2 text-sm font-medium text-muted-foreground">
          All {jobIds.length} versions. Pick the one you like best.
        </h2>
      )}
      <ul className="grid gap-4 md:grid-cols-3">
        {jobIds.map((id, index) => (
          <li key={id}>
            <VariantCard
              letter={VARIANT_LETTERS[index] ?? String(index + 1)}
              jobId={id}
              state={variants[id]}
              angle={angleLabel(meta, id)}
              hook={hookFor(meta, id, variants[id]?.job)}
              picked={picked === id}
              retrying={retrying === id}
              sourceUrl={meta?.source === "link" ? meta.input : variants[id]?.job?.source_url}
              onPick={() => handlePick(id)}
              onRetry={() => void handleRetry(id)}
            />
          </li>
        ))}
      </ul>

      <div className="flex flex-wrap gap-3 border-t border-border pt-5">
        <Button asChild variant="outline" size="sm">
          <Link href="/create">
            <Plus className="size-4" aria-hidden /> Make 3 more
          </Link>
        </Button>
        <Button asChild variant="ghost" size="sm">
          <Link href="/reels">Go to My reels</Link>
        </Button>
      </div>

      {readyCount > 0 && (
        <PlanUpsell
          reason="after_reel"
          refreshKey={readyCount}
          fallback={<BuyCredits lead="Want more reels like these? Top up in one click." />}
        />
      )}
      <PaywallMoment jobIds={jobIds} job={heroJob} ready={allTerminal && readyCount > 0} />
    </div>
  );
}

interface VariantCardProps {
  readonly letter: string;
  readonly jobId: string;
  readonly state?: VariantState;
  readonly angle: string;
  readonly hook: string;
  readonly picked: boolean;
  readonly retrying: boolean;
  readonly sourceUrl?: string;
  readonly onPick: () => void;
  readonly onRetry: () => void;
}

function VariantCard({
  letter,
  jobId,
  state,
  angle,
  hook,
  picked,
  retrying,
  sourceUrl,
  onPick,
  onRetry,
}: VariantCardProps) {
  const job = state?.job;
  const phase = variantPhase(job);
  const badge = PHASE_BADGE[phase];
  const resultUrl = job ? jobResultUrl(job) : undefined;
  const poster = job ? jobThumbnailUrl(job) : undefined;

  return (
    <Card className={cn("h-full", picked && "border-primary ring-2 ring-primary/40")}>
      <CardContent className="flex h-full flex-col gap-3 p-4">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-semibold">Variant {letter}</span>
          <Badge variant={badge.variant}>{badge.label}</Badge>
        </div>
        {angle && <p className="text-xs uppercase tracking-wide text-muted-foreground">{angle}</p>}
        <p className="min-h-[2.5rem] text-sm font-medium leading-snug">
          {hook ? `"${hook}"` : <span className="text-muted-foreground">Hook appears once the script is written.</span>}
        </p>

        <div className="relative aspect-[9/16] w-full overflow-hidden rounded-md bg-secondary">
          {phase === "ready" && resultUrl ? (
            <video
              src={resultUrl}
              poster={poster}
              controls
              playsInline
              preload="metadata"
              className="h-full w-full object-cover"
            >
              <track kind="captions" />
            </video>
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 p-4 text-center">
              {phase === "failed" ? (
                <AlertCircle className="size-6 text-destructive" aria-hidden />
              ) : (
                <Loader2 className="size-6 animate-spin text-muted-foreground" aria-hidden />
              )}
              <p className="text-sm text-muted-foreground">{currentStageLabel(job)}</p>
              {phase !== "failed" && (
                <Progress value={variantProgress(job)} className="w-3/4" aria-label={`Variant ${letter} progress`} />
              )}
              {renderingEtaLabel(job) && (
                <p className="text-xs text-muted-foreground">{renderingEtaLabel(job)}</p>
              )}
            </div>
          )}
        </div>

        {state?.error && (
          <p className="text-xs text-destructive" role="alert">
            {state.error}
          </p>
        )}

        {phase === "failed" && (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              {job?.error ? `${safeServerText(job.error, "This reel could not be finished.")} ` : ""}The credit for this reel was refunded automatically.
            </p>
            {job?.retry_eligible !== false && (
              <Button type="button" size="sm" variant="outline" onClick={onRetry} disabled={retrying}>
                {retrying ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <RefreshCw className="size-4" aria-hidden />
                )}
                Try again (1 credit)
              </Button>
            )}
          </div>
        )}

        {phase === "ready" && (
          <div className="mt-auto grid grid-cols-2 gap-2">
            <Button
              type="button"
              size="sm"
              variant={picked ? "default" : "outline"}
              onClick={onPick}
              aria-pressed={picked}
              className="col-span-2"
            >
              <Star className="size-4" aria-hidden />
              {picked ? "Picked" : "Pick this one"}
            </Button>
            <Button asChild size="sm" variant="outline">
              <Link href={`/editor?job=${encodeURIComponent(jobId)}`}>
                <Pencil className="size-4" aria-hidden /> Edit
              </Link>
            </Button>
            <Button asChild size="sm" variant="outline">
              <Link href={`/publish?job=${encodeURIComponent(jobId)}`}>
                <Send className="size-4" aria-hidden /> Publish
              </Link>
            </Button>
            {resultUrl && (
              <Button asChild size="sm" variant="ghost" className="col-span-2">
                <a href={resultUrl} download={`menivor-variant-${letter.toLowerCase()}.mp4`}>
                  <Download className="size-4" aria-hidden /> Download MP4
                </a>
              </Button>
            )}
            {resultUrl && (
              <ShareToX
                className="col-span-2"
                hook={hook}
                hashtags={job?.hashtags}
                sourceUrl={sourceUrl || job?.source_url}
                downloadUrl={resultUrl}
                downloadFilename={`menivor-variant-${letter.toLowerCase()}.mp4`}
              />
            )}
          </div>
        )}

        <Link
          href={`/jobs/${encodeURIComponent(jobId)}`}
          className="text-xs text-muted-foreground underline-offset-4 hover:underline"
        >
          Full details
        </Link>
      </CardContent>
    </Card>
  );
}
