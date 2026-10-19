import * as React from "react";
import {
  Clapperboard,
  Coins,
  DollarSign,
  Layers,
  Timer,
  TrendingDown,
} from "lucide-react";
import type { Insights } from "@/lib/types";
import { StatCard } from "./StatCard";
import { formatCount, formatDuration, formatUsd } from "./format";

export interface InsightsStatsProps {
  insights: Readonly<Insights>;
}

/**
 * The headline stat-card grid for the insights dashboard. Derives each already
 * formatted metric from the caller-scoped {@link Insights} payload.
 */
export function InsightsStats({ insights }: Readonly<InsightsStatsProps>) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <StatCard
        label="Jobs total"
        value={formatCount(insights.jobs_total)}
        icon={Layers}
        accent="primary"
      />
      <StatCard
        label="Videos generated"
        value={formatCount(insights.videos_generated)}
        hint="Successfully rendered reels"
        icon={Clapperboard}
        accent="success"
      />
      <StatCard
        label="Credits balance"
        value={formatCount(insights.credits_balance)}
        hint={`${formatCount(insights.credits_spent)} spent to date`}
        icon={Coins}
        accent="accent"
      />
      <StatCard
        label="Credits spent"
        value={formatCount(insights.credits_spent)}
        icon={TrendingDown}
        accent="destructive"
      />
      <StatCard
        label="Total cost"
        value={formatUsd(insights.total_cost_usd)}
        hint="Cumulative render spend"
        icon={DollarSign}
        accent="primary"
      />
      <StatCard
        label="Avg. render time"
        value={formatDuration(insights.avg_render_ms)}
        hint="Compose stage, per reel"
        icon={Timer}
        accent="accent"
      />
    </div>
  );
}
