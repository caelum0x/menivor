"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { FeedTrend } from "./api";

interface TrendKindSectionProps {
  title: string;
  description: string;
  trends: FeedTrend[];
  loading: boolean;
  /** Limit displayed rows — defaults to 6 */
  limit?: number;
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
      <div className="relative h-1.5 w-16 overflow-hidden rounded-full bg-muted">
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-primary"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="tabular-nums text-xs font-semibold text-primary">
        {pct}%
      </span>
    </div>
  );
}

/**
 * A compact card listing a slice of the live trends feed filtered to one kind
 * (sound | hashtag | format). Clicking a trend row navigates to /trends for
 * the full explorer.
 */
export function TrendKindSection({
  title,
  description,
  trends,
  loading,
  limit = 6,
}: TrendKindSectionProps) {
  const shown = trends.slice(0, limit);

  return (
    <Card>
      <CardContent className="space-y-4 py-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-semibold">{title}</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
          </div>
          <Link
            href="/trends"
            className="flex shrink-0 items-center gap-1 text-xs text-primary hover:underline"
          >
            All trends <ArrowRight className="h-3 w-3" aria-hidden />
          </Link>
        </div>

        {loading && (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        )}

        {!loading && shown.length === 0 && (
          <p className="py-4 text-center text-sm text-muted-foreground">
            No data yet — check back soon.
          </p>
        )}

        {!loading && shown.length > 0 && (
          <ul className="divide-y rounded-lg border">
            {shown.map((t) => (
              <li
                key={t.id ?? t.trend_id}
                className="flex items-center justify-between gap-3 px-3 py-2.5"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {t.label || t.trend_id}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <OpportunityBar value={t.opportunity} />
                  <Badge variant={phaseVariant(t.phase)} className="text-xs">
                    {t.phase}
                  </Badge>
                  {t.recommend && (
                    <Badge variant="secondary" className="text-xs">
                      build now
                    </Badge>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
