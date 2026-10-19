"use client";

import * as React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslations } from "@/lib/i18n/context";

import type { FeedTrend } from "./api";

interface TrendDeepListProps {
  trends: FeedTrend[];
  loading: boolean;
  error: string;
  emptyMessage: string;
  onRefresh: () => void;
}

function phaseVariant(
  phase: string,
): "default" | "secondary" | "outline" | "destructive" {
  if (phase === "rising") return "default";
  if (phase === "emerging") return "secondary";
  if (phase === "peaking") return "outline";
  return "destructive";
}

function OpportunityBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2">
      <div
        className="relative h-1.5 w-20 overflow-hidden rounded-full bg-muted"
        role="meter"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Opportunity ${pct}%`}
      >
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-primary transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-9 tabular-nums text-right text-xs font-semibold text-primary">
        {pct}%
      </span>
    </div>
  );
}

function SaturationBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const colorClass =
    pct >= 80
      ? "bg-destructive"
      : pct >= 50
        ? "bg-yellow-500"
        : "bg-green-500";
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-1.5 w-20 overflow-hidden rounded-full bg-muted">
        <div
          className={`absolute inset-y-0 left-0 rounded-full transition-all ${colorClass}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-9 tabular-nums text-right text-xs text-muted-foreground">
        {pct}%
      </span>
    </div>
  );
}

/**
 * Full-depth list of same-kind trends with opportunity + saturation bars,
 * phase badge, and a build-now indicator. Used by the /discover/* sub-pages.
 */
export function TrendDeepList({
  trends,
  loading,
  error,
  emptyMessage,
  onRefresh,
}: TrendDeepListProps) {
  const t = useTranslations();

  if (loading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-14 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-5 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
          <div>
            <p>{error}</p>
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={onRefresh}
            >
              <RefreshCw className="mr-2 h-3.5 w-3.5" aria-hidden />
              {t("common.tryAgain")}
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (trends.length === 0) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          {emptyMessage}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-1">
      {/* Column headers */}
      <div className="grid grid-cols-[1fr_auto] items-center gap-4 px-3 pb-1 sm:grid-cols-[1fr_auto_auto_auto]">
        <span className="text-xs font-medium text-muted-foreground">Trend</span>
        <span className="hidden text-xs font-medium text-muted-foreground sm:block">
          {t("discover.opportunityScore")}
        </span>
        <span className="hidden text-xs font-medium text-muted-foreground sm:block">
          {t("discover.saturationLabel")}
        </span>
        <span className="hidden text-xs font-medium text-muted-foreground sm:block">
          {t("discover.phaseLabel")}
        </span>
      </div>

      <ul className="divide-y rounded-lg border">
        {trends.map((trend, idx) => (
          <li
            key={trend.id ?? trend.trend_id}
            className="grid grid-cols-[1fr_auto] items-center gap-3 px-3 py-3 sm:grid-cols-[1fr_auto_auto_auto]"
          >
            {/* Rank + label */}
            <div className="flex min-w-0 items-center gap-2.5">
              <span className="w-6 shrink-0 tabular-nums text-right text-xs text-muted-foreground">
                {idx + 1}
              </span>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">
                  {trend.label || trend.trend_id}
                </p>
                {trend.recommend && (
                  <span className="text-xs font-medium text-primary">
                    {t("discover.buildNowLabel")}
                  </span>
                )}
              </div>
            </div>

            {/* Opportunity — hidden on mobile, shown compactly below */}
            <div className="hidden sm:block">
              <OpportunityBar value={trend.opportunity} />
            </div>

            {/* Saturation */}
            <div className="hidden sm:block">
              <SaturationBar value={trend.saturation} />
            </div>

            {/* Phase badge — visible always */}
            <div className="flex items-center gap-1.5">
              <Badge variant={phaseVariant(trend.phase)} className="text-xs">
                {trend.phase}
              </Badge>
              {/* Mobile-only opportunity pill */}
              <span className="tabular-nums text-xs font-semibold text-primary sm:hidden">
                {Math.round(trend.opportunity * 100)}%
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
