"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Clapperboard, Info, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslations } from "@/lib/i18n/context";

import { useDiscoverKind, useViralTemplates } from "./use-discover";
import { TrendDeepList } from "./TrendDeepList";
import type { TemplateSummary } from "./api";

function TemplateCard({ template }: { template: TemplateSummary }) {
  return (
    <Card className="flex flex-col">
      <CardContent className="flex flex-1 flex-col gap-2 py-4">
        <div className="flex items-start justify-between gap-2">
          <p className="font-medium leading-tight">{template.name}</p>
          <Badge variant="outline" className="shrink-0 text-xs">
            {template.genre}
          </Badge>
        </div>
        {template.description && (
          <p className="line-clamp-2 text-xs text-muted-foreground">
            {template.description}
          </p>
        )}
        <div className="mt-auto flex flex-wrap gap-1">
          {template.tags.slice(0, 5).map((tag) => (
            <Badge key={tag} variant="secondary" className="text-xs">
              {tag}
            </Badge>
          ))}
        </div>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{template.layout}</span>
          <span>{template.default_duration_s}s</span>
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * Rising formats sub-page (/discover/creators).
 *
 * There is no per-creator analytics endpoint in the API. This page surfaces
 * the two closest available signals:
 *   1. Format-kind trends from GET /trends/recommended — rising format patterns
 *      scored by the same velocity/saturation/opportunity model as sounds and
 *      hashtags.
 *   2. Viral shot-templates from GET /templates — proven genre formats ready to
 *      scaffold into a reel, useful for discovering which creative styles are
 *      gaining traction.
 *
 * Both are named honestly so the operator knows what they are looking at.
 */
export function FormatsPage() {
  const t = useTranslations();

  const {
    trends,
    loading: trendsLoading,
    error: trendsError,
    refresh: refreshTrends,
  } = useDiscoverKind("format", 60);

  const {
    templates,
    loading: templatesLoading,
    error: templatesError,
    refresh: refreshTemplates,
  } = useViralTemplates();

  const loading = trendsLoading || templatesLoading;

  function handleRefresh() {
    void refreshTrends();
    void refreshTemplates();
  }

  return (
    <main className="mx-auto max-w-4xl space-y-8 px-4 py-8">
      {/* Back link */}
      <Link
        href="/discover"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        {t("discover.backToDiscover")}
      </Link>

      {/* Header */}
      <header className="space-y-1">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Clapperboard className="h-6 w-6 text-primary" aria-hidden />
            <h1 className="text-2xl font-semibold">
              {t("discover.formatsPageTitle")}
            </h1>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={loading}
          >
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden />
            {t("discover.refresh")}
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          {t("discover.formatsPageSubtitle")}
        </p>
      </header>

      {/* Honest signal note */}
      <div className="flex items-start gap-2 rounded-lg border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        <p>{t("discover.formatsSignalNote")}</p>
      </div>

      {/* Format-kind trends */}
      <section className="space-y-4">
        <h2 className="font-semibold">{t("discover.viralFormats")}</h2>
        <p className="text-xs text-muted-foreground">
          {t("discover.viralFormatsDesc")}
        </p>
        <TrendDeepList
          trends={trends}
          loading={trendsLoading}
          error={trendsError}
          emptyMessage={t("discover.formatsEmpty")}
          onRefresh={() => void refreshTrends()}
        />
      </section>

      {/* Viral templates gallery */}
      <section className="space-y-4">
        <h2 className="font-semibold">{t("discover.trendingTemplates")}</h2>
        <p className="text-xs text-muted-foreground">
          {t("discover.trendingTemplatesDesc")}
        </p>

        {templatesLoading && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-28 w-full rounded-lg" />
            ))}
          </div>
        )}

        {!templatesLoading && templatesError && (
          <Card>
            <CardContent className="py-6 text-center text-sm text-destructive">
              <p>{templatesError}</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => void refreshTemplates()}
              >
                {t("common.tryAgain")}
              </Button>
            </CardContent>
          </Card>
        )}

        {!templatesLoading && !templatesError && templates.length === 0 && (
          <Card>
            <CardContent className="py-8 text-center text-sm text-muted-foreground">
              {t("discover.noDataSoon")}
            </CardContent>
          </Card>
        )}

        {!templatesLoading && !templatesError && templates.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {templates.map((tmpl) => (
              <TemplateCard key={tmpl.slug} template={tmpl} />
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
