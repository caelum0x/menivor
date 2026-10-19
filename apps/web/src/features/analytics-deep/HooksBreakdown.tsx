"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth/clerk-safe";
import {
  AlertTriangle,
  Lightbulb,
  RefreshCw,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslations } from "@/lib/i18n/context";
import type {
  Analytics,
  AnalyticsHookCount,
  AnalyticsTemplateCount,
  AnalyticsWindowDays,
} from "@/lib/types";
import {
  ANALYTICS_WINDOW_DAYS,
  ANALYTICS_DEFAULT_DAYS,
} from "@/lib/types";
import { ApiError } from "@/src/shared/api";
import { Select } from "@/components/ui/select";

import { getAnalyticsDeep } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "idle" | "loading" | "ready" | "error";

function toWindowDays(value: string): AnalyticsWindowDays {
  const parsed = Number(value);
  return (ANALYTICS_WINDOW_DAYS as readonly number[]).includes(parsed)
    ? (parsed as AnalyticsWindowDays)
    : ANALYTICS_DEFAULT_DAYS;
}

function HookRow({
  hook,
  count,
  rank,
}: Readonly<{ hook: string; count: number; rank: number }>) {
  return (
    <div className="flex items-start gap-3 py-2">
      <span className="mt-0.5 w-5 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
        {rank}.
      </span>
      <p className="flex-1 text-sm">{hook}</p>
      <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
        ×{count}
      </span>
    </div>
  );
}

function TemplateRow({
  name,
  count,
  rank,
}: Readonly<{ name: string; count: number; rank: number }>) {
  return (
    <div className="flex items-center gap-3 py-2">
      <span className="w-5 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
        {rank}.
      </span>
      <p className="flex-1 text-sm capitalize">{name.replace(/_/g, " ")}</p>
      <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
        ×{count}
      </span>
    </div>
  );
}

function HooksContent({
  analytics,
}: Readonly<{ analytics: Analytics }>) {
  const t = useTranslations();
  const { hooks, templates } = analytics.top_content;

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {/* Hooks */}
      <Card>
        <CardContent className="p-5">
          <h3 className="mb-3 font-semibold">{t("analyticsDeep.hooks.hooksHeading")}</h3>
          {hooks.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("analyticsDeep.hooks.noData")}
            </p>
          ) : (
            <div className="divide-y divide-border">
              {hooks.map((entry: AnalyticsHookCount, i: number) => (
                <HookRow
                  key={`${entry.hook}-${i}`}
                  hook={entry.hook}
                  count={entry.count}
                  rank={i + 1}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Templates */}
      <Card>
        <CardContent className="p-5">
          <h3 className="mb-3 font-semibold">
            {t("analyticsDeep.hooks.templatesHeading")}
          </h3>
          {templates.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("analyticsDeep.hooks.noData")}
            </p>
          ) : (
            <div className="divide-y divide-border">
              {templates.map((entry: AnalyticsTemplateCount, i: number) => (
                <TemplateRow
                  key={`${entry.name}-${i}`}
                  name={entry.name}
                  count={entry.count}
                  rank={i + 1}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Top hooks breakdown — most-used opening lines and templates, all-time.
 *
 * The backend's top_content is all-time (not window-scoped), so the window
 * selector only affects the funnel/cost context shown above the tables.
 * We still pass the window to the analytics call for consistency.
 */
export function HooksBreakdown() {
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
          friendlyErrorMessage(err, "Could not load hooks data.");
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
            <Lightbulb className="h-6 w-6 text-primary" aria-hidden />
            <h1 className="text-2xl font-semibold">
              {t("analyticsDeep.hooks.title")}
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <label htmlFor="hooks-window" className="sr-only">
              Time window
            </label>
            <Select
              id="hooks-window"
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
          {t("analyticsDeep.hooks.subtitle")}
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
            href="/analytics/retention"
            className="text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            {t("analyticsDeep.retention.title")}
          </Link>
        </div>
      </header>

      {status === "loading" && (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="space-y-2 p-5">
                <Skeleton className="h-5 w-28" />
                {Array.from({ length: 5 }).map((__, j) => (
                  <Skeleton key={j} className="h-4 w-full" />
                ))}
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
            <div>
              <p className="text-sm">{errorMessage}</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => void load(days)}
              >
                {t("common.tryAgain")}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {status === "ready" && analytics && (
        <HooksContent analytics={analytics} />
      )}
    </main>
  );
}
