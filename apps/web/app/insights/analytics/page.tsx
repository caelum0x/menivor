"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { AlertTriangle, LineChart, RefreshCw } from "lucide-react";
import { ApiError, getAnalytics } from "@/lib/api";
import {
  ANALYTICS_DEFAULT_DAYS,
  ANALYTICS_WINDOW_DAYS,
  type Analytics,
  type AnalyticsWindowDays,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { AnalyticsDashboard } from "@/components/analytics/AnalyticsDashboard";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

/** Narrow a raw string to a supported window, falling back to the default. */
function toWindowDays(value: string): AnalyticsWindowDays {
  const parsed = Number(value);
  return (ANALYTICS_WINDOW_DAYS as readonly number[]).includes(parsed)
    ? (parsed as AnalyticsWindowDays)
    : ANALYTICS_DEFAULT_DAYS;
}

/** Growth › Analytics — the full creator BI dashboard over a chosen window. */
export default function InsightsAnalyticsPage() {
  const { getToken, isLoaded } = useAuth();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [analytics, setAnalytics] = React.useState<Analytics | null>(null);
  const [days, setDays] = React.useState<AnalyticsWindowDays>(
    ANALYTICS_DEFAULT_DAYS,
  );
  const [errorMessage, setErrorMessage] = React.useState<string>("");

  const load = React.useCallback(
    async (windowDays: AnalyticsWindowDays) => {
      setStatus("loading");
      setErrorMessage("");
      try {
        const token = (await getToken()) ?? undefined;
        const result = await getAnalytics(windowDays, { token });
        setAnalytics(result);
        setStatus("ready");
      } catch (err) {
        const message =
          friendlyErrorMessage(err, "Something went wrong loading your analytics.");
        setErrorMessage(message);
        setStatus("error");
      }
    },
    [getToken],
  );

  React.useEffect(() => {
    if (isLoaded) void load(days);
  }, [isLoaded, days, load]);

  return (
    <>
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <LineChart className="size-6 text-primary" aria-hidden />
            Analytics
          </h1>
          <p className="text-sm text-muted-foreground">
            Your funnel, spend, credit burn, render performance, and usage
            breakdowns.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="analytics-window" className="sr-only">
            Time window
          </label>
          <Select
            id="analytics-window"
            className="w-36"
            value={String(days)}
            onChange={(event) => setDays(toWindowDays(event.target.value))}
            disabled={status === "loading"}
          >
            {ANALYTICS_WINDOW_DAYS.map((option) => (
              <option key={option} value={option}>
                Last {option} days
              </option>
            ))}
          </Select>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load(days)}
            disabled={status === "loading"}
          >
            <RefreshCw
              className={status === "loading" ? "size-4 animate-spin" : "size-4"}
              aria-hidden
            />
            Refresh
          </Button>
        </div>
      </div>

      {status === "loading" && <AnalyticsSkeleton />}

      {status === "error" && (
        <ErrorPanel message={errorMessage} onRetry={() => void load(days)} />
      )}

      {status === "ready" && analytics && (
        <AnalyticsDashboard analytics={analytics} />
      )}
    </>
  );
}

function AnalyticsSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
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
      <div className="grid gap-4 lg:grid-cols-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="space-y-4 p-6">
              <Skeleton className="h-5 w-28" />
              <Skeleton className="h-28 w-full rounded-md" />
            </CardContent>
          </Card>
        ))}
      </div>
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
            <p className="font-medium">Couldn&apos;t load your analytics</p>
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
