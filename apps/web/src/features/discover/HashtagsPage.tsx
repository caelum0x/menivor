"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Hash, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useTranslations } from "@/lib/i18n/context";

import { useDiscoverKind } from "./use-discover";
import { TrendDeepList } from "./TrendDeepList";

/**
 * Rising hashtags sub-page (/discover/hashtags).
 *
 * Fetches the live recommended-trends feed and filters to kind === "hashtag".
 * Shows opportunity + saturation bars and phase so the operator can pick
 * hashtags before they saturate the feed.
 */
export function HashtagsPage() {
  const t = useTranslations();
  const { trends, loading, error, refresh } = useDiscoverKind("hashtag", 60);

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
            <Hash className="h-6 w-6 text-primary" aria-hidden />
            <h1 className="text-2xl font-semibold">
              {t("discover.hashtagsPageTitle")}
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
          {t("discover.hashtagsPageSubtitle")}
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
        emptyMessage={t("discover.hashtagsEmpty")}
        onRefresh={() => void refresh()}
      />
    </main>
  );
}
