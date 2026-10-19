"use client";

import * as React from "react";
import { LineChart as LineChartIcon } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AnalyticsCostPoint } from "@/lib/types";
import { formatDay, formatUsd } from "./format";
import { AXIS_TICK, CHART_COLORS } from "./chart-theme";
import { ChartTooltip } from "./ChartTooltip";

export interface CostOverTimeProps {
  /** Ascending day buckets of summed render spend. */
  points: readonly AnalyticsCostPoint[];
}

/**
 * Day-by-day render spend as a filled Recharts area chart with gridlines, a
 * currency Y-axis and a themed hover tooltip. Sparse X-axis ticks keep long
 * windows legible. Falls back to a friendly empty state when nothing was spent.
 */
export function CostOverTime({ points }: Readonly<CostOverTimeProps>) {
  const total = points.reduce((sum, p) => sum + p.cost_usd, 0);
  // Recharts needs a mutable array; keep a plain copy of the read-only input.
  const data = React.useMemo(
    () => points.map((p) => ({ date: p.date, cost_usd: p.cost_usd })),
    [points],
  );
  // Show at most ~6 X-axis labels so a 90-day window doesn't crowd the axis.
  const tickInterval = Math.max(0, Math.ceil(data.length / 6) - 1);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <LineChartIcon className="size-4 text-muted-foreground" aria-hidden />
          Cost over time
        </CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 || total === 0 ? (
          <p className="text-sm text-muted-foreground">
            No render spend recorded in this window.
          </p>
        ) : (
          <div>
            <p className="mb-3 text-sm text-muted-foreground">
              <span className="font-semibold text-foreground tabular-nums">
                {formatUsd(total)}
              </span>{" "}
              total across {data.length} day{data.length === 1 ? "" : "s"}
            </p>
            <div
              className="h-40 w-full"
              role="img"
              aria-label={`Daily render spend, ${formatUsd(total)} total across ${data.length} days`}
            >
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={data}
                  margin={{ top: 4, right: 8, bottom: 0, left: -8 }}
                >
                  <defs>
                    <linearGradient id="costFill" x1="0" y1="0" x2="0" y2="1">
                      <stop
                        offset="0%"
                        stopColor={CHART_COLORS.primary}
                        stopOpacity={0.5}
                      />
                      <stop
                        offset="100%"
                        stopColor={CHART_COLORS.primary}
                        stopOpacity={0.02}
                      />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke={CHART_COLORS.grid}
                    vertical={false}
                  />
                  <XAxis
                    dataKey="date"
                    tickFormatter={formatDay}
                    tick={AXIS_TICK}
                    interval={tickInterval}
                    tickLine={false}
                    axisLine={{ stroke: CHART_COLORS.grid }}
                    minTickGap={16}
                  />
                  <YAxis
                    tick={AXIS_TICK}
                    tickFormatter={(v: number) => formatUsd(v)}
                    tickLine={false}
                    axisLine={false}
                    width={56}
                  />
                  <Tooltip
                    cursor={{ stroke: CHART_COLORS.primary, strokeOpacity: 0.3 }}
                    content={
                      <ChartTooltip format={formatUsd} labelFormat={formatDay} />
                    }
                  />
                  <Area
                    type="monotone"
                    dataKey="cost_usd"
                    name="Spend"
                    stroke={CHART_COLORS.primary}
                    strokeWidth={2}
                    fill="url(#costFill)"
                    dot={false}
                    activeDot={{ r: 3 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
