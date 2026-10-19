"use client";

import { LEADERBOARD_METRICS } from "@/lib/types";
import type { LeaderboardMetric } from "@/lib/types";
import { cn } from "@/lib/utils";
import { metricLabel } from "@/components/creators/format";

export interface MetricTabsProps {
  /** The currently-selected ranking metric. */
  value: LeaderboardMetric;
  onChange: (metric: LeaderboardMetric) => void;
  /** Disables the tabs while a refetch is in flight. */
  disabled?: boolean;
}

/**
 * A row of pill buttons for choosing the leaderboard's ranking metric. Iterates
 * the canonical {@link LEADERBOARD_METRICS} union so it never drifts from the
 * backend-accepted set.
 */
export function MetricTabs({
  value,
  onChange,
  disabled = false,
}: Readonly<MetricTabsProps>) {
  return (
    <div
      role="tablist"
      aria-label="Rank creators by"
      className="flex flex-wrap gap-2"
    >
      {LEADERBOARD_METRICS.map((metric) => {
        const active = metric === value;
        return (
          <button
            key={metric}
            type="button"
            role="tab"
            aria-selected={active}
            disabled={disabled}
            onClick={() => onChange(metric)}
            className={cn(
              "rounded-full border px-3 py-1 text-sm font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              "disabled:cursor-not-allowed disabled:opacity-60",
              active
                ? "border-transparent bg-primary text-primary-foreground"
                : "border-border text-muted-foreground hover:bg-secondary/60",
            )}
          >
            {metricLabel(metric)}
          </button>
        );
      })}
    </div>
  );
}
