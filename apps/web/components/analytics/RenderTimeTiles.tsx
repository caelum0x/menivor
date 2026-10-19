import * as React from "react";
import { Gauge, Timer, TrendingUp } from "lucide-react";
import type { AnalyticsRenderTime } from "@/lib/types";
import { StatCard } from "@/components/insights/StatCard";
import { formatCount, formatDuration } from "./format";

export interface RenderTimeTilesProps {
  renderTime: Readonly<AnalyticsRenderTime>;
}

/**
 * Render-time distribution tiles: p50 / p90 / average of the compose+upload
 * stage `duration_ms`, plus the number of render samples measured.
 */
export function RenderTimeTiles({ renderTime }: Readonly<RenderTimeTilesProps>) {
  const sampleHint = `${formatCount(renderTime.samples)} render${
    renderTime.samples === 1 ? "" : "s"
  } measured`;

  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <StatCard
        label="Render p50"
        value={formatDuration(renderTime.p50_ms)}
        hint="Median render time"
        icon={Gauge}
        accent="success"
      />
      <StatCard
        label="Render p90"
        value={formatDuration(renderTime.p90_ms)}
        hint="Slowest 10% start here"
        icon={TrendingUp}
        accent="primary"
      />
      <StatCard
        label="Render avg"
        value={formatDuration(renderTime.avg_ms)}
        hint={sampleHint}
        icon={Timer}
        accent="accent"
      />
    </div>
  );
}
