"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import Link from "next/link";
import { AlertTriangle, ArrowRight, BarChart3, RefreshCw, Trophy } from "lucide-react";
import { ApiError, getInsights } from "@/lib/api";
import type { Insights } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { InsightsStats } from "@/components/insights/InsightsStats";
import { StateBreakdown } from "@/components/insights/StateBreakdown";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

/** Growth overview — reel production, spend, and render performance headline. */
export default function InsightsPage() {
  const { getToken, isLoaded } = useAuth();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [insights, setInsights] = React.useState<Insights | null>(null);
  const [errorMessage, setErrorMessage] = React.useState<string>("");

  const load = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = (await getToken()) ?? undefined;
      const result = await getInsights({ token });
      setInsights(result);
      setStatus("ready");
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Something went wrong loading your insights.");
      setErrorMessage(message);
      setStatus("error");
    }
  }, [getToken]);

  React.useEffect(() => {
    if (isLoaded) void load();
  }, [isLoaded, load]);

  return (
    <>
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <BarChart3 className="size-6 text-primary" aria-hidden />
            Insights
          </h1>
          <p className="text-sm text-muted-foreground">
            Your reel production, spend, and render performance at a glance.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void load()}
          disabled={status === "loading"}
        >
          <RefreshCw
            className={status === "loading" ? "size-4 animate-spin" : "size-4"}
            aria-hidden
          />
          Refresh
        </Button>
      </div>

      {status === "loading" && <InsightsSkeleton />}

      {status === "error" && (
        <ErrorPanel message={errorMessage} onRetry={() => void load()} />
      )}

      {status === "ready" && insights && (
        <div className="space-y-6">
          <InsightsStats insights={insights} />
          <Link href="/insights/winners" className="group block">
            <Card className="transition-colors group-hover:border-primary/50">
              <CardContent className="flex items-center justify-between gap-4 p-5">
                <div className="flex items-start gap-3">
                  <Trophy className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
                  <div>
                    <p className="font-medium">Winner loop</p>
                    <p className="text-sm text-muted-foreground">
                      Post your variants, compare their real numbers after 48 hours, and remake the
                      winner into three new hooks.
                    </p>
                  </div>
                </div>
                <ArrowRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              </CardContent>
            </Card>
          </Link>
          <div className="grid gap-4 lg:grid-cols-2">
            <StateBreakdown jobsByState={insights.jobs_by_state} />
          </div>
        </div>
      )}
    </>
  );
}

function InsightsSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="flex items-start justify-between gap-3 p-5">
              <div className="w-full space-y-2">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-7 w-20" />
                <Skeleton className="h-3 w-28" />
              </div>
              <Skeleton className="size-9 rounded-lg" />
            </CardContent>
          </Card>
        ))}
      </div>
      <Card>
        <CardContent className="space-y-4 p-6">
          <Skeleton className="h-5 w-28" />
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-2 w-full rounded-full" />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function ErrorPanel({
  message,
  onRetry,
}: Readonly<{ message: string; onRetry: () => void }>) {
  return (
    <Card className="border-destructive/40 bg-destructive/5">
      <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <AlertTriangle
            className="mt-0.5 size-5 shrink-0 text-destructive"
            aria-hidden
          />
          <div>
            <p className="font-medium">Couldn&apos;t load your insights</p>
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
