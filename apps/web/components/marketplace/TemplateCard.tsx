"use client";

import * as React from "react";
import {
  AlertCircle,
  Check,
  Copy,
  GitFork,
  Languages,
  Layout as LayoutIcon,
  Loader2,
  Network,
  Trophy,
  Users,
} from "lucide-react";
import type { MarketplaceLineage, MarketplaceTemplate } from "@/lib/types";
import { ApiError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { LineageDialog } from "@/components/marketplace/LineageDialog";
import { StarRating } from "@/components/marketplace/StarRating";
import {
  formatCount,
  formatRating,
  formatWinScore,
  languageLabel,
  layoutLabel,
} from "@/components/marketplace/format";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface TemplateCardProps {
  template: Readonly<MarketplaceTemplate>;
  /** Clones the listing into the caller's private templates. */
  onClone: (id: string) => Promise<unknown>;
  /** Upserts the caller's rating; resolves with the fresh listing aggregate. */
  onRate: (id: string, stars: number) => Promise<MarketplaceTemplate>;
  /** Fetches this listing's remix-tree lineage (ancestors + children). */
  onLineage: (id: string) => Promise<MarketplaceLineage>;
}

type CloneState =
  | { status: "idle" }
  | { status: "cloning" }
  | { status: "cloned" }
  | { status: "error"; message: string };

type RateState =
  | { status: "idle" }
  | { status: "rating" }
  | { status: "error"; message: string };

const MAX_TAGS = 4;

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * A single marketplace listing. Shows the snapshot metadata, aggregate rating,
 * clone-count, an interactive "your rating" row (upserts, one per user), and a
 * Clone button. Rating updates the card's local aggregate immutably from the
 * server response; each action carries its own loading + error state.
 */
export function TemplateCard({
  template,
  onClone,
  onRate,
  onLineage,
}: Readonly<TemplateCardProps>) {
  const [aggregate, setAggregate] = React.useState({
    ratingAvg: template.rating_avg,
    ratingCount: template.rating_count,
    viewerStars:
      typeof template.viewer_stars === "number" ? template.viewer_stars : 0,
  });
  const [clone, setClone] = React.useState<CloneState>({ status: "idle" });
  const [rate, setRate] = React.useState<RateState>({ status: "idle" });
  const [lineageOpen, setLineageOpen] = React.useState(false);

  const handleClone = React.useCallback(async () => {
    setClone({ status: "cloning" });
    try {
      await onClone(template.id);
      setClone({ status: "cloned" });
    } catch (err) {
      setClone({
        status: "error",
        message: errorMessage(err, "Couldn't clone this template."),
      });
    }
  }, [onClone, template.id]);

  const handleRate = React.useCallback(
    async (stars: number) => {
      setRate({ status: "rating" });
      try {
        const updated = await onRate(template.id, stars);
        setAggregate({
          ratingAvg: updated.rating_avg,
          ratingCount: updated.rating_count,
          viewerStars:
            typeof updated.viewer_stars === "number"
              ? updated.viewer_stars
              : stars,
        });
        setRate({ status: "idle" });
      } catch (err) {
        setRate({
          status: "error",
          message: errorMessage(err, "Couldn't save your rating."),
        });
      }
    },
    [onRate, template.id],
  );

  const cloned = clone.status === "cloned";
  const visibleTags = template.tags.slice(0, MAX_TAGS);
  const extraTags = template.tags.length - visibleTags.length;
  const winScore = formatWinScore(template.win_score);
  const remixCount =
    typeof template.remix_count === "number" ? template.remix_count : 0;
  const isRemix = Boolean(template.parent_template_id);

  return (
    <>
    <Card className="flex h-full flex-col">
      <CardContent className="flex flex-1 flex-col gap-4 p-5">
        <div className="space-y-1.5">
          <div className="flex items-start justify-between gap-3">
            <h3 className="text-base font-semibold leading-snug">
              {template.title || "Untitled template"}
            </h3>
            <span
              className="flex shrink-0 items-center gap-1 text-sm font-medium tabular-nums"
              title={`${formatCount(aggregate.ratingCount)} rating${
                aggregate.ratingCount === 1 ? "" : "s"
              }`}
            >
              <StarRating value={aggregate.ratingAvg} size="size-3.5" />
              <span className="text-muted-foreground">
                {formatRating(aggregate.ratingAvg)}
              </span>
            </span>
          </div>
          {template.description && (
            <p className="line-clamp-2 text-sm text-muted-foreground">
              {template.description}
            </p>
          )}
        </div>

        {visibleTags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {visibleTags.map((tag) => (
              <Badge key={tag} variant="secondary">
                {tag}
              </Badge>
            ))}
            {extraTags > 0 && <Badge variant="outline">+{extraTags}</Badge>}
          </div>
        )}

        <div className="flex flex-wrap gap-1.5">
          {template.layout && (
            <Badge variant="outline">
              <LayoutIcon className="size-3" aria-hidden />
              {layoutLabel(template.layout)}
            </Badge>
          )}
          <Badge variant="outline">
            <Languages className="size-3" aria-hidden />
            {languageLabel(template.language)}
          </Badge>
          <Badge variant="outline">
            <Users className="size-3" aria-hidden />
            {formatCount(template.clone_count)} clone
            {template.clone_count === 1 ? "" : "s"}
          </Badge>
          <Badge
            variant="outline"
            title="How many times this template has been remixed"
          >
            <GitFork className="size-3" aria-hidden />
            {formatCount(remixCount)} remix{remixCount === 1 ? "" : "es"}
          </Badge>
          {isRemix && (
            <Badge
              variant="secondary"
              title="This template was remixed from another listing"
            >
              <Network className="size-3" aria-hidden />
              Remix
            </Badge>
          )}
          {winScore !== null && (
            <Badge
              variant="success"
              title="Real-world win-score aggregated from downstream reels"
            >
              <Trophy className="size-3" aria-hidden />
              Win {winScore}
            </Badge>
          )}
        </div>

        <div className="mt-auto space-y-3 pt-2">
          <div className="flex items-center justify-between gap-3">
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">Your rating</p>
              <StarRating
                value={aggregate.viewerStars}
                onRate={handleRate}
                disabled={rate.status === "rating"}
              />
            </div>
            {rate.status === "rating" && (
              <Loader2
                className="size-4 animate-spin text-muted-foreground"
                aria-label="Saving rating"
              />
            )}
          </div>

          {rate.status === "error" && (
            <p
              role="alert"
              className="flex items-center gap-1.5 text-xs text-destructive"
            >
              <AlertCircle className="size-3.5 shrink-0" aria-hidden />
              {rate.message}
            </p>
          )}

          {clone.status === "error" && (
            <p
              role="alert"
              className="flex items-center gap-1.5 text-xs text-destructive"
            >
              <AlertCircle className="size-3.5 shrink-0" aria-hidden />
              {clone.message}
            </p>
          )}

          <Button
            type="button"
            size="sm"
            variant={cloned ? "outline" : "default"}
            className="w-full"
            onClick={() => void handleClone()}
            disabled={clone.status === "cloning" || cloned}
          >
            {clone.status === "cloning" ? (
              <>
                <Loader2 className="animate-spin" aria-hidden /> Cloning…
              </>
            ) : cloned ? (
              <>
                <Check aria-hidden /> Cloned to your templates
              </>
            ) : (
              <>
                <Copy aria-hidden /> Clone template
              </>
            )}
          </Button>

          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="w-full"
            onClick={() => setLineageOpen(true)}
          >
            <Network aria-hidden /> View remix tree
          </Button>
        </div>
      </CardContent>
    </Card>

      <LineageDialog
        open={lineageOpen}
        onClose={() => setLineageOpen(false)}
        template={template}
        onLoad={onLineage}
      />
    </>
  );
}
