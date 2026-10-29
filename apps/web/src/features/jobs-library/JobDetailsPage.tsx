"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/clerk-safe";
import {
  AlertTriangle,
  ArrowLeft,
  Download,
  KeyRound,
  MonitorUp,
  RefreshCw,
  RotateCcw,
  Scissors,
  Send,
  X,
} from "lucide-react";
import {
  ApiError,
  getJob,
  jobDisplayTitle,
  POLL_INTERVAL_MS,
  retryJob,
} from "@/lib/api";
import {
  isFailedState,
  isTerminalState,
  JOB_STAGES,
  type Job,
  type JobStage,
} from "@/lib/types";
import {
  jobPreviewUrl,
  jobResultUrl,
  jobThumbnailUrl,
} from "@/lib/job-media";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { JobStatusBadge } from "./components/JobStatusBadge";
import { StageProgress } from "./components/StageProgress";
import { JobPreview } from "./components/JobPreview";
import { RerunPanel } from "./components/RerunPanel";
import { ScheduledForJob } from "./components/ScheduledForJob";
import { DubButton } from "@/components/dub/DubButton";
import { SchedulePublishButton } from "@/components/schedule/SchedulePublishButton";
import { CoverEditor } from "@/components/cover/CoverEditor";
import { BrollPanel } from "@/components/broll/BrollPanel";
import { SocialPanel } from "@/components/social/SocialPanel";
import { ShareButton } from "@/components/share/ShareButton";
import { ReelActions } from "@/src/features/reels-library/components/ReelActions";
import { useReelActions } from "@/src/features/reels-library/use-reel-actions";
import { MenivorMark } from "@/components/brand/MenivorMark";
import { ShareActions } from "@/src/features/share-actions/ShareActions";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { safeServerText } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

/**
 * The URL scheme the Menivor desktop editor (Chop) registers. The editor
 * accepts exactly `menivor-editor://open?job=<id>` and fetches the reel with
 * the API key the person signed in with there.
 */
const DESKTOP_EDITOR_SCHEME = "menivor-editor";
/** Where the desktop editor installer is published. Optional: without it the
 * help panel explains sign-in and the manual import path only. */
const DESKTOP_DOWNLOAD_URL =
  process.env.NEXT_PUBLIC_DESKTOP_DOWNLOAD_URL?.trim() || "/editor";
/** How long to wait for the browser to hand focus to the desktop app before
 * assuming it is not installed. */
const DESKTOP_LAUNCH_TIMEOUT_MS = 1800;

/**
 * Whether the API attached the desktop editor's clip descriptor. The backend
 * only includes `generated_clip` for a completed reel whose clean result the
 * caller may access, so it is exactly the "openable in the editor" signal.
 */
function hasGeneratedClip(job: Job): boolean {
  const clip = (job as Job & { generated_clip?: unknown }).generated_clip;
  return typeof clip === "object" && clip !== null;
}

/**
 * Fires the desktop editor link and reports whether the app took focus.
 * Browsers expose no success signal for custom schemes, so a window blur or
 * the page becoming hidden within the timeout counts as "opened". Returns a
 * cancel function that removes the listeners.
 */
function launchDesktopEditor(
  jobId: string,
  onResult: (opened: boolean) => void,
): () => void {
  let settled = false;
  const onBlur = () => finish(true);
  const onVisibility = () => {
    if (document.visibilityState === "hidden") finish(true);
  };
  const timer = window.setTimeout(
    () => finish(false),
    DESKTOP_LAUNCH_TIMEOUT_MS,
  );
  function cleanup() {
    window.removeEventListener("blur", onBlur);
    document.removeEventListener("visibilitychange", onVisibility);
    window.clearTimeout(timer);
  }
  function finish(opened: boolean) {
    if (settled) return;
    settled = true;
    cleanup();
    onResult(opened);
  }
  window.addEventListener("blur", onBlur);
  document.addEventListener("visibilitychange", onVisibility);
  window.location.href = `${DESKTOP_EDITOR_SCHEME}://open?job=${encodeURIComponent(jobId)}`;
  return () => {
    settled = true;
    cleanup();
  };
}

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err, fallback);
  if (err instanceof Error) return friendlyErrorMessage(err, fallback);
  return fallback;
}

export function JobDetailsPage() {
  const params = useParams<{ id: string }>();
  const id = typeof params.id === "string" ? params.id : "";
  const { getToken, isLoaded } = useAuth();
  const router = useRouter();

  const [job, setJob] = React.useState<Job | null>(null);
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [loadError, setLoadError] = React.useState<string>("");
  const [actionError, setActionError] = React.useState<string>("");
  const [retrying, setRetrying] = React.useState(false);
  // Latest cover generated in-session; preferred over the job's stored cover.
  const [coverUrl, setCoverUrl] = React.useState<string | undefined>(undefined);
  // Bumping this restarts the polling effect (after a retry or manual reload).
  const [reloadNonce, setReloadNonce] = React.useState(0);

  // Poll GET /jobs/{id} every 3s until the state is terminal (§ contract).
  React.useEffect(() => {
    if (!isLoaded || !id) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    const tick = async (): Promise<void> => {
      try {
        const token = (await getToken()) ?? undefined;
        const next = await getJob(id, { token, signal: controller.signal });
        if (cancelled) return;
        // Keep the in-session cancel receipt (refund amount) across polls.
        setJob((prev) =>
          prev?.cancelled && prev.job_id === next.job_id
            ? { ...next, cancelled: true, refunded_credits: prev.refunded_credits }
            : next,
        );
        setStatus("ready");
        setLoadError("");
        if (!isTerminalState(next.state)) {
          timer = setTimeout(() => void tick(), POLL_INTERVAL_MS);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setLoadError(errorMessageOf(err, "Failed to load this job."));
        setStatus("error");
      }
    };

    setStatus((prev) => (prev === "ready" ? prev : "loading"));
    void tick();

    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [isLoaded, id, getToken, reloadNonce]);

  const handleRetry = React.useCallback(async () => {
    setRetrying(true);
    setActionError("");
    try {
      const token = (await getToken()) ?? undefined;
      const updated = await retryJob(id, { token });
      setJob(updated);
      setStatus("ready");
      // Restart polling from the re-enqueued state.
      setReloadNonce((n) => n + 1);
    } catch (err) {
      setActionError(errorMessageOf(err, "Failed to retry this job."));
    } finally {
      setRetrying(false);
    }
  }, [getToken, id]);

  const reload = React.useCallback(() => {
    setReloadNonce((n) => n + 1);
  }, []);

  // Rename / archive / cancel / delete. A cancel returns a terminal job, which
  // also stops the polling loop on its next tick.
  const handleJobUpdated = React.useCallback((updated: Job) => {
    setJob(updated);
  }, []);
  const handleJobRemoved = React.useCallback(() => {
    setJob(null);
  }, []);
  const reelActions = useReelActions(handleJobUpdated, handleJobRemoved);

  // Reel thumbnail: the in-session generated cover wins, else the job's stored
  // cover, else the poster frame.
  const thumbnailUrl = coverUrl ?? (job ? jobThumbnailUrl(job) : undefined);
  const previewUrl = job ? jobPreviewUrl(job) : undefined;
  const resultUrl = job ? jobResultUrl(job) : undefined;

  const isComplete =
    !!job && isTerminalState(job.state) && !isFailedState(job.state);

  // Hide the upload stage when the job finished without it (no platforms).
  const visibleStages = React.useMemo<readonly JobStage[]>(() => {
    if (
      job &&
      isTerminalState(job.state) &&
      job.stages &&
      !("upload" in job.stages)
    ) {
      return JOB_STAGES.filter((s) => s !== "upload");
    }
    return JOB_STAGES;
  }, [job]);

  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link href="/reels" className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft className="size-4" aria-hidden /> Back to library
          </Link>
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
        </div>
      </header>

      <section className="container max-w-3xl py-8">
        {status === "loading" && !job && <DetailSkeleton />}

        {status === "error" && !job && (
          <LoadErrorPanel message={loadError} onRetry={reload} />
        )}

        {job && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0 space-y-2">
                <h1 className="text-2xl font-bold tracking-tight">
                  <span className="block truncate">{jobDisplayTitle(job)}</span>
                  <span className="block font-mono text-sm font-normal text-muted-foreground">
                    {job.job_id.slice(0, 12)}
                    {job.archived ? " · archived" : ""}
                  </span>
                </h1>
                <p className="text-sm text-muted-foreground">
                  {job.cancelled
                    ? `Cancelled.${
                        typeof job.refunded_credits === "number" && job.refunded_credits > 0
                          ? ` ${job.refunded_credits} credit${job.refunded_credits === 1 ? "" : "s"} returned to your balance.`
                          : ""
                      }`
                    : isTerminalState(job.state)
                      ? "Rendering finished."
                      : "Live — refreshing every 3 seconds."}
                </p>
                <ReelActions
                  job={job}
                  actions={reelActions}
                  labelled
                  onDeleted={() => router.push("/reels")}
                  align="start"
                />
              </div>
              <div className="flex flex-col items-end gap-1.5">
                <JobStatusBadge
                  state={job.state}
                  className="px-3 py-1 text-sm"
                />
                <DubButton job={job} />
                <SchedulePublishButton job={job} />
              </div>
            </div>

            {loadError && (
              <p className="text-xs text-muted-foreground">
                Live updates paused: {loadError}{" "}
                <button
                  type="button"
                  onClick={reload}
                  className="underline underline-offset-2 hover:text-foreground"
                >
                  Resume
                </button>
              </p>
            )}

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Overall progress</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <Progress value={job.progress} />
                <p className="text-sm text-muted-foreground">{job.progress}%</p>
              </CardContent>
            </Card>

            {isFailedState(job.state) && (
              <FailurePanel
                job={job}
                retrying={retrying}
                actionError={actionError}
                onRetry={handleRetry}
              />
            )}

            {job.media_blocked && (
              <Card role="status">
                <CardContent className="py-6 text-sm text-muted-foreground">
                  {job.media_blocked_message ||
                    "This video is paused while we review a report about it."}{" "}
                  Questions: support@menivor.com.
                </CardContent>
              </Card>
            )}

            {resultUrl && (
              <VideoPreview
                url={resultUrl}
                posterUrl={thumbnailUrl}
                editHref={`/editor?job=${encodeURIComponent(job.job_id)}`}
                publishHref={`/publish?job=${encodeURIComponent(job.job_id)}`}
                jobId={job.job_id}
                desktopReady={isComplete && hasGeneratedClip(job)}
              />
            )}

            {!resultUrl && previewUrl && (
              <JobPreview previewUrl={previewUrl} posterUrl={thumbnailUrl} />
            )}

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Pipeline stages</CardTitle>
              </CardHeader>
              <CardContent>
                <StageProgress
                  stages={job.stages}
                  visibleStages={visibleStages}
                />
              </CardContent>
            </Card>

            {isComplete && (
              <CoverEditor
                job={job}
                onGenerated={(result) => setCoverUrl(result.cover_url)}
              />
            )}

            {isComplete && <BrollPanel job={job} />}

            {isComplete && <SocialPanel job={job} />}

            {isComplete && <ScheduledForJob jobId={job.job_id} />}

            {isTerminalState(job.state) && <RerunPanel job={job} />}
          </div>
        )}
      </section>
    </main>
  );
}

function VideoPreview({
  url,
  posterUrl,
  editHref,
  publishHref,
  jobId,
  desktopReady,
}: Readonly<{
  url: string;
  posterUrl?: string;
  editHref: string;
  publishHref: string;
  jobId: string;
  /** The reel carries a desktop-editor clip descriptor. */
  desktopReady: boolean;
}>) {
  // "launching": the link fired, waiting to see if the app took focus.
  // "help": the app did not respond (or the person asked how it works).
  const [desktop, setDesktop] = React.useState<"idle" | "launching" | "help">(
    "idle",
  );
  const [notDetected, setNotDetected] = React.useState(false);
  const cancelLaunch = React.useRef<(() => void) | null>(null);

  React.useEffect(() => () => cancelLaunch.current?.(), []);

  const openInDesktop = React.useCallback(() => {
    cancelLaunch.current?.();
    setDesktop("launching");
    cancelLaunch.current = launchDesktopEditor(jobId, (opened) => {
      cancelLaunch.current = null;
      setNotDetected(!opened);
      setDesktop(opened ? "idle" : "help");
    });
  }, [jobId]);

  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
        <CardTitle className="text-base">Preview</CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <Link href={editHref}>
              <Scissors className="size-4" aria-hidden /> Edit reel
            </Link>
          </Button>
          {desktopReady && (
            <Button
              variant="outline"
              size="sm"
              onClick={openInDesktop}
              disabled={desktop === "launching"}
            >
              <MonitorUp className="size-4" aria-hidden />
              {desktop === "launching" ? "Opening…" : "Open in Chop"}
            </Button>
          )}
          <Button asChild variant="outline" size="sm">
            <Link href={publishHref}>
              <Send className="size-4" aria-hidden /> Publish now
            </Link>
          </Button>
          <ShareButton jobId={jobId} />
          <ShareActions source="reel" sourceId={jobId} kind="video" />
          <Button asChild variant="outline" size="sm">
            <a href={url} download target="_blank" rel="noopener noreferrer">
              <Download className="size-4" aria-hidden /> Download
            </a>
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {desktopReady && desktop === "help" && (
          <DesktopEditorHelp
            downloadUrl={url}
            notDetected={notDetected}
            onRetry={openInDesktop}
            onClose={() => {
              setDesktop("idle");
              setNotDetected(false);
            }}
          />
        )}
        <div className="mx-auto w-full max-w-[320px] overflow-hidden rounded-lg border border-border bg-black">
          {/* 9:16 portrait reel. */}
          <video
            src={url}
            poster={posterUrl}
            controls
            playsInline
            preload="metadata"
            className="aspect-[9/16] h-auto w-full"
          >
            Your browser does not support the video tag.{" "}
            <a href={url}>Download the video</a> instead.
          </video>
        </div>
        {desktopReady && desktop !== "help" && (
          <p className="text-center text-xs text-muted-foreground">
            <button
              type="button"
              onClick={() => {
                setNotDetected(false);
                setDesktop("help");
              }}
              className="underline underline-offset-2 hover:text-foreground"
            >
              How does the desktop editor work?
            </button>
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Shown when the desktop editor did not respond to its link, or on request:
 * how to install it, sign in, retry, and the manual download-and-import path.
 */
function DesktopEditorHelp({
  downloadUrl,
  notDetected,
  onRetry,
  onClose,
}: Readonly<{
  downloadUrl: string;
  notDetected: boolean;
  onRetry: () => void;
  onClose: () => void;
}>) {
  return (
    <div
      role="region"
      aria-label="Desktop editor help"
      className="rounded-lg border border-border bg-secondary/30 p-4 text-sm"
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 font-medium">
          <MonitorUp className="size-4 text-primary" aria-hidden />
          Open this reel in Chop
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close desktop editor help"
          className="text-muted-foreground hover:text-foreground"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      {notDetected && (
        <p className="mb-3 text-muted-foreground">
          Chop did not respond. If it is not installed yet, set it up below
          and try again.
        </p>
      )}
      <ol className="mb-4 list-decimal space-y-2 pl-5 text-muted-foreground">
        {DESKTOP_DOWNLOAD_URL && (
          <li>
            <a
              href={DESKTOP_DOWNLOAD_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-foreground underline underline-offset-2"
            >
              Download Chop
            </a>{" "}
            for macOS, Windows or Linux and install it.
          </li>
        )}
        <li>
          Create an API key on the{" "}
          <Link
            href="/settings/api-keys"
            className="inline-flex items-center gap-1 font-medium text-foreground underline underline-offset-2"
          >
            <KeyRound className="size-3.5" aria-hidden />
            API keys
          </Link>{" "}
          page. When the editor asks you to sign in to Menivor, paste it there.
          The key stays in your computer&apos;s credential store.
        </li>
        <li>
          Come back here and choose Open in Chop. Your browser may ask to
          allow Chop to open the link.
        </li>
      </ol>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={onRetry}>
          <RefreshCw className="size-4" aria-hidden /> Try opening again
        </Button>
        <Button asChild variant="outline" size="sm">
          <a
            href={downloadUrl}
            download
            target="_blank"
            rel="noopener noreferrer"
          >
            <Download className="size-4" aria-hidden /> Download MP4 instead
          </a>
        </Button>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        Prefer to do it by hand? Download the MP4, start a project in Menivor
        Editor and import the file into its media bin.
      </p>
    </div>
  );
}

function FailurePanel({
  job,
  retrying,
  actionError,
  onRetry,
}: Readonly<{
  job: Job;
  retrying: boolean;
  actionError: string;
  onRetry: () => void;
}>) {
  return (
    <Card className="border-destructive/40 bg-destructive/5">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base text-destructive">
          <AlertTriangle className="size-5" aria-hidden />
          Rendering failed
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-destructive">
          {safeServerText(job.error, "Something went wrong while making this reel. Please try again.")}
        </p>
        {actionError && (
          <p className="text-sm text-destructive">{actionError}</p>
        )}
        <Button onClick={onRetry} disabled={retrying}>
          <RotateCcw
            className={retrying ? "size-4 animate-spin" : "size-4"}
            aria-hidden
          />
          {retrying ? "Retrying…" : "Retry job"}
        </Button>
      </CardContent>
    </Card>
  );
}

function LoadErrorPanel({
  message,
  onRetry,
}: Readonly<{ message: string; onRetry: () => void }>) {
  return (
    <Card className="border-destructive/40 bg-destructive/5">
      <CardContent className="flex flex-col items-start gap-4 p-6">
        <div className="flex items-start gap-3">
          <AlertTriangle
            className="mt-0.5 size-5 shrink-0 text-destructive"
            aria-hidden
          />
          <div>
            <p className="font-medium">Couldn&apos;t load this job</p>
            <p className="text-sm text-muted-foreground">{message}</p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="size-4" aria-hidden /> Try again
        </Button>
      </CardContent>
    </Card>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-7 w-28 rounded-full" />
      </div>
      <Skeleton className="h-28 w-full rounded-lg" />
      <Skeleton className="h-64 w-full rounded-lg" />
    </div>
  );
}
