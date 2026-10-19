"use client";

import * as React from "react";
import Link from "next/link";
import { ExternalLink, Trophy } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatMeasuredRate, isMeasured, NOT_MEASURED_HINT } from "@/src/features/experiments";
import { formatCount, formatPct, platformLabel } from "./format";
import type { LoopVariant } from "./types";

const SOURCE_LABELS: Record<LoopVariant["source"], string> = {
  platform: "From platform",
  logged: "Logged by you",
  none: "No data yet",
};

export interface VariantRankingProps {
  variants: readonly LoopVariant[];
  usesRetention: boolean;
  rankingReason: string;
}

/** Variants ranked by the loop's score, with per-platform numbers and data notes. */
export function VariantRanking({
  variants,
  usesRetention,
  rankingReason,
}: Readonly<VariantRankingProps>) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Variant ranking</CardTitle>
        <p className="text-sm text-muted-foreground">
          Ranked on {usesRetention ? "average watch share, views and engagement rate" : "views and engagement rate"}.
          Engagement rate is likes, comments, shares and saves per view; the platforms do not
          report a click-through rate for organic short videos.
          {rankingReason ? ` ${rankingReason}.` : ""}
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {variants.map((variant) => (
          <div
            key={variant.job_id}
            className={cn(
              "rounded-lg border p-4",
              variant.is_winner ? "border-primary/60 bg-primary/5" : "border-border",
            )}
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 space-y-1">
                <p className="flex items-center gap-2 text-xs text-muted-foreground">
                  {variant.rank !== null ? `#${variant.rank}` : "Unranked"}
                  {variant.is_winner && (
                    <Badge variant="success">
                      <Trophy className="size-3" aria-hidden /> Winner
                    </Badge>
                  )}
                  <span>{SOURCE_LABELS[variant.source]}</span>
                </p>
                <p className="font-medium leading-snug">{variant.hook || variant.title}</p>
              </div>
              <Link
                href={`/jobs/${encodeURIComponent(variant.job_id)}`}
                className="shrink-0 text-sm text-primary underline-offset-4 hover:underline"
              >
                Open reel
              </Link>
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4 lg:grid-cols-7">
              <Metric label="Views" value={formatCount(variant.views)} />
              <Metric label="Avg watch" value={formatPct(variant.avg_watch_frac)} />
              <RateMetric label="Completion" value={variant.completion_rate} />
              <RateMetric label="Rewatch" value={variant.rewatch_rate} />
              <Metric label="Engagement" value={formatPct(variant.engagement_rate)} />
              <Metric label="Shares" value={formatCount(variant.shares)} />
              <Metric label="Score" value={variant.score !== null ? variant.score.toFixed(2) : "—"} />
            </dl>
            {variant.posts.length > 0 && (
              <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
                {variant.posts.map((post) => (
                  <li key={`${post.platform}-${post.external_id}`} className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-foreground">{platformLabel(post.platform)}</span>
                    {post.available ? (
                      <span>{formatCount(post.views)} views</span>
                    ) : (
                      <span>metrics unavailable</span>
                    )}
                    {post.note && <span>· {post.note}</span>}
                    {post.url && (
                      <a
                        href={post.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-primary"
                      >
                        View post <ExternalLink className="size-3" aria-hidden />
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {variant.state !== "complete" && (
              <p className="mt-2 text-xs text-muted-foreground">Render status: {variant.state}</p>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="rounded-md bg-secondary/40 px-2 py-1.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-semibold">{value}</dd>
    </div>
  );
}

/** A rate the platform may not report: null renders as "not measured", never 0%. */
function RateMetric({ label, value }: Readonly<{ label: string; value: number | null | undefined }>) {
  const measured = isMeasured(value);
  return (
    <div className="rounded-md bg-secondary/40 px-2 py-1.5" title={measured ? undefined : NOT_MEASURED_HINT}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={measured ? "font-semibold" : "text-xs font-medium text-muted-foreground"}>
        {formatMeasuredRate(value)}
      </dd>
    </div>
  );
}
