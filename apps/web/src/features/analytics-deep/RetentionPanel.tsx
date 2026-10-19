"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth/clerk-safe";
import {
  AlertTriangle,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  Timer,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Select } from "@/components/ui/select";
import { useTranslations } from "@/lib/i18n/context";
import {
  ANALYTICS_WINDOW_DAYS,
  ANALYTICS_DEFAULT_DAYS,
  type Analytics,
  type AnalyticsWindowDays,
} from "@/lib/types";
import { ApiError } from "@/src/shared/api";

import { getAnalyticsDeep } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "idle" | "loading" | "ready" | "error";

function toWindowDays(value: string): AnalyticsWindowDays {
  const parsed = Number(value);
  return (ANALYTICS_WINDOW_DAYS as readonly number[]).includes(parsed)
    ? (parsed as AnalyticsWindowDays)
    : ANALYTICS_DEFAULT_DAYS;
}

function StatTile({
  label,
  value,
  sub,
  intent,
}: Readonly<{
  label: string;
  value: string | number;
  sub?: string;
  intent?: "positive" | "negative" | "neutral";
}>) {
  const colour =
    intent === "positive"
      ? "text-green-600 dark:text-green-400"
      : intent === "negative"
        ? "text-destructive"
        : "text-primary";
  return (
    <Card>
      <CardContent className="p-5">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={`mt-1 text-2xl font-bold tabular-nums ${colour}`}>
          {value}
        </p>
        {sub && (
          <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>
        )}
      </CardContent>
    </Card>
  );
}

function FunnelBar({
  label,
  count,
  total,
}: Readonly<{ label: string; count: number; total: number }>) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span>{label}</span>
        <span className="tabular-nums">
          {count}{" "}
          <span className="text-xs text-muted-foreground">({pct}%)</span>
        </span>
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

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${(s / 60).toFixed(1)}min`;
}

function RetentionContent({
  analytics,
}: Readonly<{ analytics: Analytics }>) {
  const t = useTranslations();
  const { funnel, render_time, totals } = analytics;
  const completionRate =
    funnel.created > 0
      ? Math.round((funnel.completed / funnel.created) * 100)
      : 0;
  const failRate =
    funnel.created > 0
      ? Math.round((funnel.failed / funnel.created) * 100)
      : 0;

  return (
    <div className="space-y-6">
      {/* KPI tiles */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label={t("analyticsDeep.retention.completionRate")}
          value={`${completionRate}%`}
          sub={`${funnel.completed} of ${funnel.created}`}
          intent={completionRate >= 80 ? "positive" : completionRate >= 50 ? "neutral" : "negative"}
        />
        <StatTile
          label={t("analyticsDeep.retention.failRate")}
          value={`${failRate}%`}
          sub={`${funnel.failed} failed`}
          intent={failRate === 0 ? "positive" : failRate > 10 ? "negative" : "neutral"}
        />
        <StatTile
          label={t("analyticsDeep.retention.published")}
          value={funnel.published}
          sub={`${funnel.created > 0 ? Math.round((funnel.published / funnel.created) * 100) : 0}% of created`}
          intent="neutral"
        />
        <StatTile
          label={totals.jobs_total === 1 ? "Total job" : "Total jobs"}
          value={totals.jobs_total}
          sub={`${analytics.days}-day window`}
          intent="neutral"
        />
      </div>

      {/* Funnel */}
      <Card>
        <CardContent className="space-y-4 p-5">
          <h3 className="font-semibold">{t("analyticsDeep.retention.title")}</h3>
          <div className="space-y-3">
            <FunnelBar
              label={t("analyticsDeep.retention.created")}
              count={funnel.created}
              total={funnel.created}
            />
            <FunnelBar
              label={t("analyticsDeep.retention.completed")}
              count={funnel.completed}
              total={funnel.created}
            />
            <FunnelBar
              label={t("analyticsDeep.retention.published")}
              count={funnel.published}
              total={funnel.created}
            />
            <FunnelBar
              label={t("analyticsDeep.retention.failed")}
              count={funnel.failed}
              total={funnel.created}
            />
          </div>
        </CardContent>
      </Card>

      {/* Render time */}
      {render_time.samples > 0 && (
        <Card>
          <CardContent className="p-5">
            <div className="mb-4 flex items-center gap-2">
              <Timer className="h-4 w-4 text-primary" aria-hidden />
              <h3 className="font-semibold">{t("analyticsDeep.retention.renderTime")}</h3>
              <span className="text-xs text-muted-foreground">
                ({render_time.samples} {t("analyticsDeep.retention.samples")})
              </span>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <p className="text-xs text-muted-foreground">
                  {t("analyticsDeep.retention.p50")}
                </p>
                <p className="mt-1 text-lg font-bold tabular-nums">
                  {formatMs(render_time.p50_ms)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">
                  {t("analyticsDeep.retention.p90")}
                </p>
                <p className="mt-1 text-lg font-bold tabular-nums">
                  {formatMs(render_time.p90_ms)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">
                  {t("analyticsDeep.retention.avg")}
                </p>
                <p className="mt-1 text-lg font-bold tabular-nums">
                  {formatMs(render_time.avg_ms)}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {funnel.created === 0 && (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            {t("analyticsDeep.retention.noData")}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/**
 * Retention and funnel panel — completion rate, render-time percentiles,
 * and funnel progression from GET /me/analytics.
 */
export function RetentionPanel() {
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
          friendlyErrorMessage(err, "Could not load retention data.");
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
      <header className="space-y-1">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-6 w-6 text-primary" aria-hidden />
            <h1 className="text-2xl font-semibold">
              {t("analyticsDeep.retention.title")}
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <label htmlFor="retention-window" className="sr-only">
              Time window
            </label>
            <Select
              id="retention-window"
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
          {t("analyticsDeep.retention.subtitle")}
        </p>
        <div className="flex items-center gap-3 pt-1">
          <Link
            href="/analytics"
            className="text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            {t("apiDocs.backToOverview")}
          </Link>
          <span className="text-xs text-muted-foreground">|</span>
          <Link
            href="/analytics/views"
            className="text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            {t("analyticsDeep.views.title")}
          </Link>
          <span className="text-xs text-muted-foreground">|</span>
          <Link
            href="/analytics/hooks"
            className="text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            {t("analyticsDeep.hooks.title")}
          </Link>
        </div>
      </header>

      {status === "loading" && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Card key={i}>
                <CardContent className="p-5">
                  <Skeleton className="h-3 w-24" />
                  <Skeleton className="mt-1 h-8 w-16" />
                </CardContent>
              </Card>
            ))}
          </div>
          <Card>
            <CardContent className="space-y-3 p-5">
              <Skeleton className="h-5 w-28" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-full" />
            </CardContent>
          </Card>
        </div>
      )}

      {status === "error" && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex items-center gap-3 p-5">
            <AlertTriangle
              className="h-5 w-5 shrink-0 text-destructive"
              aria-hidden
            />
            <div>
              <p className="text-sm">{errorMessage}</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => void load(days)}
              >
                <TrendingDown className="mr-1 h-4 w-4" aria-hidden />
                {t("common.tryAgain")}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {status === "ready" && analytics && (
        <RetentionContent analytics={analytics} />
      )}
    </main>
  );
}
