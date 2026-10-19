"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Music, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useTranslations } from "@/lib/i18n/context";

import { useDiscoverKind } from "./use-discover";
import { TrendDeepList } from "./TrendDeepList";

/**
 * Trending sounds sub-page (/discover/sounds).
 *
 * Fetches the live recommended-trends feed and filters to kind === "sound".
 * Shows opportunity + saturation bars and phase for each sound so the operator
 * can decide which to attach before the wave peaks.
 */
export function SoundsPage() {
  const t = useTranslations();
  const { trends, loading, error, refresh } = useDiscoverKind("sound", 60);

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
            <Music className="h-6 w-6 text-primary" aria-hidden />
            <h1 className="text-2xl font-semibold">
              {t("discover.soundsPageTitle")}
            </h1>
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
        <p className="text-sm text-muted-foreground">
          {t("discover.soundsPageSubtitle")}
        </p>
        {!loading && !error && (
          <p className="text-xs text-muted-foreground">
            {trends.length} trend{trends.length !== 1 ? "s" : ""} found
          </p>
        )}
      </header>

      {/* Deep list */}
      <TrendDeepList
        trends={trends}
        loading={loading}
        error={error}
        emptyMessage={t("discover.soundsEmpty")}
        onRefresh={() => void refresh()}
      />
    </main>
  );
}
