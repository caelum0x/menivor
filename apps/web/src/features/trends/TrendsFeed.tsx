"use client";

import * as React from "react";
import { AlertTriangle, Radio, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useTrendsFeed } from "./use-trends-feed";

/** Live server-ranked trends feed, rendered alongside the manual ranker. */
export function TrendsFeed() {
  const { trends, loading, error, refresh } = useTrendsFeed(20);

  return (
    <Card>
      <CardContent className="space-y-4 py-5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Radio className="h-4 w-4 text-primary" aria-hidden />
            <h2 className="font-semibold">Live feed</h2>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refresh()}
            disabled={loading}
          >
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden /> Refresh
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Server-scored rising trends, highest opportunity first.
        </p>

        {loading && (
          <div className="space-y-2">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        )}

        {!loading && error && (
          <div className="flex items-center gap-3 text-sm text-destructive">
            <AlertTriangle className="h-4 w-4" aria-hidden />
            <div>
              <p>{error}</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => void refresh()}
              >
                Try again
              </Button>
            </div>
          </div>
        )}

        {!loading && !error && trends.length === 0 && (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No live trends yet. Check back soon or rank your own below.
          </p>
        )}

        {!loading && !error && trends.length > 0 && (
          <ul className="divide-y rounded-lg border">
            {trends.map((t) => (
              <li
                key={t.id || t.trend_id}
                className="flex items-center justify-between gap-3 px-3 py-2.5"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium">{t.label || t.trend_id}</p>
                  <p className="text-xs text-muted-foreground">
                    {t.kind} · {t.phase}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="tabular-nums font-semibold text-primary">
                    {(t.opportunity * 100).toFixed(0)}%
                  </span>
                  {t.recommend ? (
                    <Badge variant="secondary">recommend</Badge>
                  ) : (
                    <Badge variant="outline">hold</Badge>
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
