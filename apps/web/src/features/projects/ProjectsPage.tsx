"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth/clerk-safe";
import {
  AlertTriangle,
  ArrowUpRight,
  Clapperboard,
  Cpu,
  Film,
  FolderOpen,
  FolderUp,
  RefreshCw,
  Scissors,
  Send,
  Sparkles,
} from "lucide-react";
import { ApiError, jobDisplayTitle, listJobsPage } from "@/lib/api";
import { JobState, isTerminalState, type Job } from "@/lib/types";
import { jobThumbnailUrl } from "@/lib/job-media";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { JobStatusBadge } from "@/src/features/jobs-library";
import { listBrollClips, type BrollClip } from "@/src/features/broll-library/api";
import { stashBrollAttachment } from "@/src/shared/media";
import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

const SECTION_LIMIT = 8;

type Section<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: readonly T[]; total: number };

function messageOf(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

function createdAt(job: Job): number {
  const t = job.created_at ? Date.parse(job.created_at) : Number.NaN;
  return Number.isNaN(t) ? 0 : t;
}

/**
 * Projects: one place for everything the caller has made — reels (GET /jobs)
 * with their edit/publish hand-offs, AI clips (GET /generation/broll/generations)
 * ready to drop into a reel, and the entry points to make more.
 */
export function ProjectsPage() {
  const { getToken, isLoaded } = useAuth();
  const [reels, setReels] = React.useState<Section<Job>>({ status: "loading" });
  const [clips, setClips] = React.useState<Section<BrollClip>>({ status: "loading" });
  const [inProgress, setInProgress] = React.useState(0);

  const load = React.useCallback(async () => {
    setReels({ status: "loading" });
    setClips({ status: "loading" });
    const token = (await getToken()) ?? undefined;
    const [jobsResult, clipsResult] = await Promise.allSettled([
      listJobsPage({ limit: 100, offset: 0 }, { token }),
      listBrollClips({ limit: 30 }, { token }),
    ]);
    if (jobsResult.status === "fulfilled") {
      const sorted = jobsResult.value.jobs
        .filter((j) => !j.archived)
        .sort((a, b) => createdAt(b) - createdAt(a));
      setInProgress(sorted.filter((j) => !isTerminalState(j.state)).length);
      setReels({ status: "ready", items: sorted.slice(0, SECTION_LIMIT), total: sorted.length });
    } else {
      setReels({ status: "error", message: messageOf(jobsResult.reason, "Could not load your reels.") });
    }
    if (clipsResult.status === "fulfilled") {
      const ready = clipsResult.value.filter((c) => c.state === JobState.Complete && c.result_url);
      setClips({ status: "ready", items: ready.slice(0, SECTION_LIMIT), total: ready.length });
    } else {
      setClips({ status: "error", message: messageOf(clipsResult.reason, "Could not load your AI clips.") });
    }
  }, [getToken]);

  React.useEffect(() => {
    if (!isLoaded) return;
    void load();
  }, [isLoaded, load]);

  return (
    <main className="min-h-dvh">
      <AppTopBar />

      <section className="container space-y-10 py-10">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="max-w-2xl">
            <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
              <FolderOpen className="size-7 text-primary" aria-hidden /> Projects
            </h1>
            <p className="mt-2 text-muted-foreground">
              Everything you&apos;ve made — reels, edits, and AI clips — with the next step one
              click away.
              {inProgress > 0 && ` ${inProgress} reel${inProgress === 1 ? " is" : "s are"} rendering now.`}
            </p>
          </div>
          <Button type="button" variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="size-4" aria-hidden /> Refresh
          </Button>
        </div>

        <ProjectSection
          title="Reels"
          icon={<Film className="size-5 text-primary" aria-hidden />}
          section={reels}
          viewAllHref="/reels"
          emptyText="No reels yet. Create one from narration, a template, or the guided wizard."
          emptyCta={{ href: "/create", label: "Create a reel" }}
          onRetry={() => void load()}
          renderItem={(job) => <ReelTile key={job.job_id} job={job} />}
        />

        <ProjectSection
          title="AI clips"
          icon={<Sparkles className="size-5 text-primary" aria-hidden />}
          section={clips}
          viewAllHref="/broll-library"
          emptyText="No finished AI clips yet. Generate one from a text prompt or an image."
          emptyCta={{ href: "/create", label: "Generate an AI video" }}
          onRetry={() => void load()}
          renderItem={(clip) => <ClipTile key={clip.generation_id} clip={clip} />}
        />

        <ShortcutCard
          icon={<Clapperboard className="size-5 text-primary" aria-hidden />}
          title="Films and series"
          body="Character-consistent multi-shot films: render each shot, then export the final cut."
          href="/film"
          cta="Open film studio"
        />

        <ShortcutCard
          icon={<FolderUp className="size-5 text-primary" aria-hidden />}
          title="Uploads"
          body="Recordings, voiceovers and photos you uploaded, ready to preview or download."
          href="/uploads"
          cta="Open uploads"
        />

        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-3 py-5">
            <div className="flex items-center gap-3">
              <Cpu className="size-5 text-primary" aria-hidden />
              <div>
                <p className="font-medium">AI video renders</p>
                <p className="text-sm text-muted-foreground">
                  GPU text-to-video renders and your recent render history.
                </p>
              </div>
            </div>
            <Button asChild variant="outline" size="sm">
              <Link href="/render">
                Open renders <ArrowUpRight className="size-4" aria-hidden />
              </Link>
            </Button>
          </CardContent>
        </Card>
      </section>
    </main>
  );
}

function ShortcutCard({
  icon,
  title,
  body,
  href,
  cta,
}: Readonly<{ icon: React.ReactNode; title: string; body: string; href: string; cta: string }>) {
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center justify-between gap-3 py-5">
        <div className="flex items-center gap-3">
          {icon}
          <div>
            <p className="font-medium">{title}</p>
            <p className="text-sm text-muted-foreground">{body}</p>
          </div>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link href={href}>
            {cta} <ArrowUpRight className="size-4" aria-hidden />
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function ProjectSection<T>({
  title,
  icon,
  section,
  viewAllHref,
  emptyText,
  emptyCta,
  onRetry,
  renderItem,
}: Readonly<{
  title: string;
  icon: React.ReactNode;
  section: Section<T>;
  viewAllHref: string;
  emptyText: string;
  emptyCta: { href: string; label: string };
  onRetry: () => void;
  renderItem: (item: T) => React.ReactNode;
}>) {
  return (
    <section aria-labelledby={`projects-${title}`} className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 id={`projects-${title}`} className="flex items-center gap-2 text-xl font-semibold">
          {icon} {title}
          {section.status === "ready" && (
            <span className="text-sm font-normal text-muted-foreground">({section.total})</span>
          )}
        </h2>
        <Link href={viewAllHref} className="text-sm text-primary underline-offset-4 hover:underline">
          View all
        </Link>
      </div>

      {section.status === "loading" && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="aspect-[9/16] rounded-lg" />
          ))}
        </div>
      )}

      {section.status === "error" && (
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          <AlertTriangle className="size-4" aria-hidden /> {section.message}
          <Button type="button" size="sm" variant="outline" onClick={onRetry}>
            Try again
          </Button>
        </div>
      )}

      {section.status === "ready" && section.items.length === 0 && (
        <div className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          <p>{emptyText}</p>
          <Button asChild size="sm" className="mt-3">
            <Link href={emptyCta.href}>{emptyCta.label}</Link>
          </Button>
        </div>
      )}

      {section.status === "ready" && section.items.length > 0 && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {section.items.map(renderItem)}
        </div>
      )}
    </section>
  );
}

function ReelTile({ job }: Readonly<{ job: Job }>) {
  const id = encodeURIComponent(job.job_id);
  const thumb = jobThumbnailUrl(job);
  const complete = job.state === JobState.Complete;
  return (
    <Card className="overflow-hidden">
      <Link href={`/reels/${id}`} className="block aspect-[9/16] bg-muted">
        {thumb ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={thumb} alt="" className="h-full w-full object-cover" loading="lazy" />
        ) : (
          <span className="flex h-full items-center justify-center">
            <Film className="size-6 text-muted-foreground" aria-hidden />
          </span>
        )}
      </Link>
      <CardContent className="space-y-2 p-3">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm">{jobDisplayTitle(job)}</span>
        </div>
        <JobStatusBadge state={job.state} />
        {complete && (
          <div className="flex flex-wrap gap-1.5">
            <Button asChild size="sm" variant="outline">
              <Link href={`/editor?job=${id}`} aria-label="Edit reel">
                <Scissors className="size-4" aria-hidden />
              </Link>
            </Button>
            <Button asChild size="sm" variant="outline">
              <Link href={`/publish?job=${id}`} aria-label="Publish reel">
                <Send className="size-4" aria-hidden />
              </Link>
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ClipTile({ clip }: Readonly<{ clip: BrollClip }>) {
  return (
    <Card className="overflow-hidden">
      <video
        src={clip.result_url}
        className="aspect-[9/16] w-full bg-black object-cover"
        muted
        playsInline
        controls
        preload="metadata"
        aria-label={`AI clip ${clip.generation_id}`}
      />
      <CardContent className="p-3">
        {clip.broll_key ? (
          <Button asChild size="sm" className="w-full">
            <Link
              href="/new"
              onClick={() =>
                stashBrollAttachment({ key: clip.broll_key, resultUrl: clip.result_url ?? "" })
              }
            >
              <Clapperboard className="size-4" aria-hidden /> Use in a reel
            </Link>
          </Button>
        ) : (
          <p className="text-xs text-muted-foreground">{clip.duration.toFixed(1)}s clip</p>
        )}
      </CardContent>
    </Card>
  );
}
