"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Clapperboard } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { TemplateSummary } from "./api";

interface TemplateTrendsSectionProps {
  templates: TemplateSummary[];
  loading: boolean;
  /** Limit displayed cards — defaults to 6 */
  limit?: number;
}

/**
 * Viral-format template grid inside the discover hub — shows the top genre
 * templates with their tags and a link into /templates for the full gallery.
 */
export function TemplateTrendsSection({
  templates,
  loading,
  limit = 6,
}: TemplateTrendsSectionProps) {
  const shown = templates.slice(0, limit);

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Clapperboard className="h-4 w-4 text-primary" aria-hidden />
          <h2 className="font-semibold">Viral formats</h2>
        </div>
        <Link
          href="/templates"
          className="flex items-center gap-1 text-xs text-primary hover:underline"
        >
          All formats <ArrowRight className="h-3 w-3" aria-hidden />
        </Link>
      </div>
      <p className="text-xs text-muted-foreground">
        Genre shot-templates the pipeline knows — each is a proven viral format
        ready to scaffold your next reel.
      </p>

      {loading && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full rounded-lg" />
          ))}
        </div>
      )}

      {!loading && shown.length === 0 && (
        <p className="py-4 text-center text-sm text-muted-foreground">
          No templates available yet.
        </p>
      )}

      {!loading && shown.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((t) => (
            <Card key={t.slug} className="flex flex-col">
              <CardContent className="flex flex-1 flex-col gap-2 py-4">
                <div className="flex items-start justify-between gap-2">
                  <p className="font-medium leading-tight">{t.name}</p>
                  <Badge variant="outline" className="shrink-0 text-xs">
                    {t.genre}
                  </Badge>
                </div>
                {t.description && (
                  <p className="line-clamp-2 text-xs text-muted-foreground">
                    {t.description}
                  </p>
                )}
                <div className="mt-auto flex flex-wrap gap-1">
                  {t.tags.slice(0, 4).map((tag) => (
                    <Badge key={tag} variant="secondary" className="text-xs">
                      {tag}
                    </Badge>
                  ))}
                </div>
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>{t.layout}</span>
                  <span>{t.default_duration_s}s</span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}
