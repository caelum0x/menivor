"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth/clerk-safe";
import {
  AlertTriangle,
  BarChart2,
  RefreshCw,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Select } from "@/components/ui/select";
import { useTranslations } from "@/lib/i18n/context";
import {
  ANALYTICS_WINDOW_DAYS,
  ANALYTICS_DEFAULT_DAYS,
  type AnalyticsWindowDays,
} from "@/lib/types";
import { ApiError } from "@/src/shared/api";

import { getAnalyticsDeep, type Analytics } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "idle" | "loading" | "ready" | "error";

function toWindowDays(value: string): AnalyticsWindowDays {
  const parsed = Number(value);
  return (ANALYTICS_WINDOW_DAYS as readonly number[]).includes(parsed)
    ? (parsed as AnalyticsWindowDays)
    : ANALYTICS_DEFAULT_DAYS;
}

function BreakdownBar({
  label,
  count,
  max,
}: Readonly<{ label: string; count: number; max: number }>) {
  const pct = max > 0 ? Math.round((count / max) * 100) : 0;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className="capitalize">{label.replace(/_/g, " ")}</span>
        <span className="tabular-nums font-medium">{count}</span>
      </div>
      <div className="relative h-2 overflow-hidden rounded-full bg-muted">
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-primary transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function BreakdownSection({
  heading,
  data,
}: Readonly<{ heading: string; data: Record<string, number> }>) {
  const t = useTranslations();
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = entries[0]?.[1] ?? 0;
  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <h3 className="font-semibold">{heading}</h3>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("analyticsDeep.views.noData")}
          </p>
        ) : (
          <div className="space-y-3">
            {entries.map(([label, count]) => (
              <BreakdownBar key={label} label={label} count={count} max={max} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Views breakdown — job counts by layout and language from GET /me/analytics.
 */
export function ViewsBreakdown() {
  const t = useTranslations();
  const { getToken, isLoaded } = useAuth();
  const [status, setStatus] = React.useState<LoadState>("idle");
  const [analytics, setAnalytics] = React.useState<Analytics | null>(null);
  const [days, setDays] = React.useState<AnalyticsWindowDays>(ANALYTICS_DEFAULT_DAYS);
  const [errorMessage, setErrorMessage] = React.useState("");

  const load = React.useCallback(
    async (windowDays: AnalyticsWindowDays) => {
      setStatus("loading");
      setErrorMessage("");
      try {
        const token = (await getToken()) ?? undefined;
        const result = await getAnalyticsDeep(windowDays, { token });
        setAnalytics(result);
        setStatus("ready");
      } catch (err) {
        const msg =
          friendlyErrorMessage(err, "Could not load views data.");
        setErrorMessage(msg);
        setStatus("error");
      }
    },
    [getToken],
  );

  React.useEffect(() => {
    if (isLoaded) void load(days);
  }, [isLoaded, days, load]);

  return (
    <main className="mx-auto max-w-4xl space-y-8 px-4 py-8">
      {/* Header */}
      <header className="space-y-1">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex items-center gap-2">
            <BarChart2 className="h-6 w-6 text-primary" aria-hidden />
            <h1 className="text-2xl font-semibold">
              {t("analyticsDeep.views.title")}
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <label htmlFor="views-window" className="sr-only">
              Time window
            </label>
            <Select
              id="views-window"
              className="w-36"
              value={String(days)}
              onChange={(e) => setDays(toWindowDays(e.target.value))}
              disabled={status === "loading"}
            >
              {ANALYTICS_WINDOW_DAYS.map((opt) => (
                <option key={opt} value={opt}>
                  Last {opt} days
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
                className={
                  status === "loading" ? "h-4 w-4 animate-spin" : "h-4 w-4"
                }
                aria-hidden
              />
              Refresh
            </Button>
          </div>
        </div>
        <p className="text-sm text-muted-foreground">
          {t("analyticsDeep.views.subtitle")}
        </p>
        <div className="pt-1">
          <Link
            href="/analytics"
            className="text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            {t("apiDocs.backToOverview")}
          </Link>
        </div>
      </header>

      {status === "loading" && (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="space-y-3 p-5">
                <Skeleton className="h-5 w-24" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {status === "error" && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex items-center gap-3 p-5">
            <AlertTriangle
              className="h-5 w-5 shrink-0 text-destructive"
              aria-hidden
            />
            <p className="text-sm">{errorMessage}</p>
          </CardContent>
        </Card>
      )}

      {status === "ready" && analytics && (
        <div className="grid gap-4 sm:grid-cols-2">
          <BreakdownSection
            heading={t("analyticsDeep.views.byLayout")}
            data={analytics.by_layout}
          />
          <BreakdownSection
            heading={t("analyticsDeep.views.byLanguage")}
            data={analytics.by_language}
          />
        </div>
      )}
    </main>
  );
}
