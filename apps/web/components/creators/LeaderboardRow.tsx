import Link from "next/link";
import { Copy, FileVideo, Star, Users } from "lucide-react";
import type { LeaderboardEntry, LeaderboardMetric } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CreatorAvatar } from "@/components/creators/CreatorAvatar";
import {
  displayName,
  formatCount,
  formatRating,
  handleLabel,
  metricLabel,
  metricValue,
} from "@/components/creators/format";

export interface LeaderboardRowProps {
  entry: Readonly<LeaderboardEntry>;
  /** The metric the board is ranked by (drives the headline value + label). */
  metric: LeaderboardMetric;
}

/** Tailwind classes for the rank chip; the top three get a podium tint. */
function rankClasses(rank: number): string {
  if (rank === 1) return "bg-accent/20 text-accent";
  if (rank === 2) return "bg-muted-foreground/15 text-foreground";
  if (rank === 3) return "bg-primary/15 text-primary";
  return "bg-secondary text-muted-foreground";
}

/**
 * One ranked creator row. The name links to the creator's public profile by
 * `user_id` (the only address the SAFE profile can be followed by — the profile
 * shape itself omits the id). Shows the headline metric plus a compact secondary
 * stat strip. Renders ONLY safe fields.
 */
export function LeaderboardRow({
  entry,
  metric,
}: Readonly<LeaderboardRowProps>) {
  const name = displayName(entry.display_name, entry.handle);
  const handle = handleLabel(entry.handle);

  return (
    <li className="flex items-center gap-3 px-4 py-3">
      <span
        aria-label={`Rank ${entry.rank}`}
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold tabular-nums",
          rankClasses(entry.rank),
        )}
      >
        {entry.rank}
      </span>

      <CreatorAvatar name={entry.display_name} handle={entry.handle} />

      <div className="min-w-0 flex-1">
        <Link
          href={`/creators/${encodeURIComponent(entry.user_id)}`}
          className="block truncate font-medium hover:underline focus-visible:underline focus-visible:outline-none"
        >
          {name}
        </Link>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
          {handle && <span className="truncate">{handle}</span>}
          <span className="inline-flex items-center gap-1">
            <Users className="size-3" aria-hidden />
            {formatCount(entry.follower_count)}
          </span>
          <span className="inline-flex items-center gap-1">
            <FileVideo className="size-3" aria-hidden />
            {formatCount(entry.published_template_count)}
          </span>
          <span className="inline-flex items-center gap-1">
            <Copy className="size-3" aria-hidden />
            {formatCount(entry.total_clones_received)}
          </span>
          <span className="inline-flex items-center gap-1">
            <Star className="size-3" aria-hidden />
            {formatRating(entry.avg_rating)}
          </span>
        </div>
      </div>

      <div className="shrink-0 text-right">
        <p className="text-lg font-semibold tabular-nums leading-none">
          {metricValue(entry, metric)}
        </p>
        <p className="mt-1 text-[11px] uppercase tracking-wide text-muted-foreground">
          {metricLabel(metric)}
        </p>
      </div>
    </li>
  );
}
