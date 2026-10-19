"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useAuth } from "@/components/auth/clerk-safe";
import {
  AlertTriangle,
  ArrowLeft,
  Layers,
  RefreshCw,
} from "lucide-react";
import { ApiError, getBatch, POLL_INTERVAL_MS } from "@/lib/api";
import { isTerminalState, JobState, type BatchJob } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { BatchGrid } from "@/components/batch/BatchGrid";
import { MenivorMark } from "@/components/brand/MenivorMark";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/** Index of the first variant that has reached Complete, or -1 if none. */
function firstFinishedIndex(jobs: readonly BatchJob[]): number {
  return jobs.findIndex((j) => j.state === JobState.Complete);
}

/** True once every variant is terminal (all rendered or failed). */
function allTerminal(jobs: readonly BatchJob[]): boolean {
  return jobs.length > 0 && jobs.every((j) => isTerminalState(j.state));
}

export default function BatchPage() {
  const params = useParams<{ id: string }>();
  const id = typeof params.id === "string" ? params.id : "";
  const { getToken, isLoaded } = useAuth();

  const [jobs, setJobs] = React.useState<readonly BatchJob[] | null>(null);
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [loadError, setLoadError] = React.useState<string>("");
  // Bumping this restarts the polling effect (after a manual reload).
  const [reloadNonce, setReloadNonce] = React.useState(0);

  // Poll GET /batches/{id} every 3s until every variant is terminal.
  React.useEffect(() => {
    if (!isLoaded || !id) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    const tick = async (): Promise<void> => {
      try {
        const token = (await getToken()) ?? undefined;
        const batch = await getBatch(id, { token, signal: controller.signal });
        if (cancelled) return;
        setJobs(batch.jobs);
        setStatus("ready");
        setLoadError("");
        if (!allTerminal(batch.jobs)) {
          timer = setTimeout(() => void tick(), POLL_INTERVAL_MS);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setLoadError(errorMessageOf(err, "Failed to load this batch."));
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

  const reload = React.useCallback(() => {
    setReloadNonce((n) => n + 1);
  }, []);

  const highlightIndex = jobs ? firstFinishedIndex(jobs) : -1;
  const finishedCount = jobs
    ? jobs.filter((j) => isTerminalState(j.state)).length
    : 0;
  const isDone = jobs ? allTerminal(jobs) : false;

  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link
            href="/reels"
            className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" aria-hidden /> Back to reels
          </Link>
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
        </div>
      </header>

      <section className="container max-w-5xl py-8">
        {status === "loading" && !jobs && <BatchSkeleton />}

        {status === "error" && !jobs && (
          <LoadErrorPanel message={loadError} onRetry={reload} />
        )}

        {jobs && jobs.length === 0 && <EmptyPanel />}

        {jobs && jobs.length > 0 && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h1 className="flex items-center gap-3 text-2xl font-bold tracking-tight">
                  <Layers className="size-6 text-primary" aria-hidden />
                  Batch review
                </h1>
                <p className="text-sm text-muted-foreground">
                  {finishedCount} of {jobs.length} variant
                  {jobs.length === 1 ? "" : "s"} finished
                  {isDone ? "." : " — refreshing every 3 seconds."}
                </p>
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

            <BatchGrid jobs={jobs} highlightIndex={highlightIndex} />
          </div>
        )}
      </section>
    </main>
  );
}

function BatchSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-8 w-48" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-80 w-full rounded-lg" />
        ))}
      </div>
    </div>
  );
}

function EmptyPanel() {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 p-10 text-center">
        <Layers className="size-8 text-muted-foreground" aria-hidden />
        <div>
          <p className="font-medium">No variants in this batch</p>
          <p className="text-sm text-muted-foreground">
            This batch has no jobs yet, or it may belong to another account.
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link href="/reels">Back to reels</Link>
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
            <p className="font-medium">Couldn&apos;t load this batch</p>
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
