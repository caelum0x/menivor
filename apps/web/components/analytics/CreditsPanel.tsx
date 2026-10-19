"use client";

import * as React from "react";
import { Coins, Flame, TrendingDown } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AnalyticsCredits } from "@/lib/types";
import { StatCard } from "@/components/insights/StatCard";
import { formatCount, formatDay } from "./format";
import { AXIS_TICK, CHART_COLORS } from "./chart-theme";
import { ChartTooltip } from "./ChartTooltip";

export interface CreditsPanelProps {
  credits: Readonly<AnalyticsCredits>;
  /** The trailing window (days) the burn covers — used only for copy. */
  days: number;
}

/**
 * Credit burn-rate + live balance. Two headline cards (live balance, spent in
 * window) plus a day-by-day burn bar chart drawn with Recharts (gridlines,
 * axes, themed hover tooltip).
 */
export function CreditsPanel({ credits, days }: Readonly<CreditsPanelProps>) {
  const perDay = days > 0 ? credits.spent / days : 0;
  const totalBurn = credits.burn_by_day.reduce((sum, p) => sum + p.spent, 0);
  // Recharts needs a mutable array; copy the read-only ledger series.
  const data = React.useMemo(
    () => credits.burn_by_day.map((p) => ({ date: p.date, spent: p.spent })),
    [credits.burn_by_day],
  );
  const tickInterval = Math.max(0, Math.ceil(data.length / 6) - 1);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <StatCard
          label="Credits balance"
          value={formatCount(credits.balance)}
          hint="Live personal balance"
          icon={Coins}
          accent="accent"
        />
        <StatCard
          label="Credits spent"
          value={formatCount(credits.spent)}
          hint={`~${formatCount(Math.round(perDay))}/day over ${days} days`}
          icon={TrendingDown}
          accent="destructive"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Flame className="size-4 text-muted-foreground" aria-hidden />
            Burn rate
          </CardTitle>
        </CardHeader>
        <CardContent>
          {data.length === 0 || totalBurn === 0 ? (
            <p className="text-sm text-muted-foreground">
              No credits spent in this window.
            </p>
          ) : (
            <div
              className="h-32 w-full"
              role="img"
              aria-label={`Daily credit burn over ${days} days`}
            >
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={data}
                  margin={{ top: 4, right: 8, bottom: 0, left: -12 }}
                >
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
                    tickFormatter={(v: number) => formatCount(v)}
                    tickLine={false}
                    axisLine={false}
                    width={40}
                    allowDecimals={false}
                  />
                  <Tooltip
                    cursor={{ fill: CHART_COLORS.destructive, fillOpacity: 0.08 }}
                    content={
                      <ChartTooltip
                        format={(v) => `${formatCount(v)} credits`}
                        labelFormat={formatDay}
                      />
                    }
                  />
                  <Bar
                    dataKey="spent"
                    name="Burned"
                    fill={CHART_COLORS.destructive}
                    radius={[2, 2, 0, 0]}
                    maxBarSize={28}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
