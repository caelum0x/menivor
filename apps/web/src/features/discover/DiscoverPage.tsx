"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, RefreshCw, TrendingUp, Zap } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslations } from "@/lib/i18n/context";

import { useDiscover } from "./use-discover";
import { TrendKindSection } from "./TrendKindSection";
import { TemplateTrendsSection } from "./TemplateTrendsSection";

/**
 * Discover hub — surfaces trending sounds, hashtags, formats, and viral
 * templates in one place. All data comes from the real API:
 *   - GET /trends/recommended  (sounds, hashtags, formats)
 *   - GET /templates           (viral genre shot-templates)
 */
export function DiscoverPage() {
  const t = useTranslations();
  const { data, loading, error, refresh } = useDiscover();

  return (
    <main className="mx-auto max-w-6xl space-y-10 px-4 py-8">
      {/* Header */}
      <header className="space-y-1">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-6 w-6 text-primary" aria-hidden />
            <h1 className="text-2xl font-semibold">{t("discover.title")}</h1>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refresh()}
            disabled={loading}
          >
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden />
            {t("discover.refresh")}
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">{t("discover.subtitle")}</p>
      </header>

      {/* Global error */}
      {!loading && error && (
        <Card>
          <CardContent className="flex items-center gap-3 py-5 text-sm text-destructive">
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
            <div>
              <p>{error}</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => void refresh()}
              >
                {t("common.tryAgain")}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Loading skeleton for the full page on first load */}
      {loading && (
        <div className="space-y-6">
          <Skeleton className="h-64 w-full rounded-lg" />
          <Skeleton className="h-64 w-full rounded-lg" />
          <Skeleton className="h-64 w-full rounded-lg" />
        </div>
      )}

      {!loading && !error && (
        <>
          {/* Top overall trends — all kinds */}
          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-primary" aria-hidden />
              <h2 className="font-semibold">{t("discover.risingNow")}</h2>
            </div>
            <p className="text-xs text-muted-foreground">
              {t("discover.risingNowDesc")}
            </p>

            {data.allTrends.length === 0 ? (
              <Card>
                <CardContent className="py-8 text-center text-sm text-muted-foreground">
                  {t("discover.noTrends")}
                </CardContent>
              </Card>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {data.allTrends.slice(0, 9).map((tr) => {
                  const pct = Math.round(tr.opportunity * 100);
                  return (
                    <Card key={tr.id ?? tr.trend_id}>
                      <CardContent className="space-y-2 py-4">
                        <div className="flex items-start justify-between gap-2">
                          <p className="truncate font-medium">
                            {tr.label || tr.trend_id}
                          </p>
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {tr.kind}
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                            <div
                              className="absolute inset-y-0 left-0 rounded-full bg-primary"
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className="tabular-nums text-xs font-semibold text-primary">
                            {pct}%
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-xs text-muted-foreground">
                          <span>{tr.phase}</span>
                          {tr.recommend && (
                            <span className="font-medium text-primary">
                              {t("discover.buildNow")}
                            </span>
                          )}
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}
          </section>

          {/* Sounds */}
          <TrendKindSection
            title={t("discover.sounds")}
            description={t("discover.soundsDesc")}
            trends={data.soundTrends}
            loading={false}
            limit={8}
          />

          {/* Hashtags */}
          <TrendKindSection
            title={t("discover.hashtags")}
            description={t("discover.hashtagsDesc")}
            trends={data.hashtagTrends}
            loading={false}
            limit={8}
          />

          {/* Viral templates */}
          <TemplateTrendsSection
            templates={data.templates}
            loading={false}
            limit={6}
          />

          {/* CTA — link to the full trends explorer */}
          <div className="rounded-lg border bg-muted/30 px-6 py-5 text-center">
            <p className="text-sm text-muted-foreground">
              {t("discover.explorerCta")}{" "}
              <Link href="/trends" className="text-primary underline-offset-2 hover:underline">
                {t("discover.explorerCtaLink")}
              </Link>{" "}
              {t("discover.explorerCtaTail")}
            </p>
          </div>
        </>
      )}
    </main>
  );
}
