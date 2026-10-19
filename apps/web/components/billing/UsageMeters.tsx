"use client";

import * as React from "react";
import { Gauge, Infinity as InfinityIcon } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { MetricOverage, Usage } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { AXIS_TICK, CHART_COLORS } from "@/components/analytics/chart-theme";
import {
  formatCount,
  formatPeriod,
  isBounded,
  metricLabel,
  metricPercent,
  usageBadgeVariant,
} from "./format";

export interface UsageMetersProps {
  usage: Usage | null;
  /** The billing month being shown (`'YYYY-MM'`). */
  period: string;
}

/**
 * Metered usage for the billing month: a Recharts overview of consumption vs
 * plan allotment for capped metrics, then a per-metric meter with an overage
 * warning. All values are the tenant's own (`GET /me/workspaces/{id}/usage`) —
 * never another workspace's rows. Unbounded metrics render as "Unlimited".
 */
export function UsageMeters({ usage, period }: Readonly<UsageMetersProps>) {
  const metrics = React.useMemo(() => usage?.overage ?? [], [usage]);
  const bounded = React.useMemo(
    () => metrics.filter((m) => isBounded(m.limit)),
    [metrics],
  );
  const chartData = React.useMemo(
    () =>
      bounded.map((m) => ({
        label: metricLabel(m.metric),
        used: Math.max(0, m.used),
        limit: isBounded(m.limit) ? m.limit : 0,
        over: m.overage > 0,
      })),
    [bounded],
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Gauge className="size-5 text-primary" aria-hidden />
              Usage
            </CardTitle>
            <CardDescription>{formatPeriod(period)}</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {metrics.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No metered usage recorded for this period yet.
          </p>
        ) : (
          <>
            {chartData.length > 0 && (
              <div
                className="h-48 w-full"
                role="img"
                aria-label={`Usage vs plan allotment for ${formatPeriod(period)}`}
              >
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    layout="vertical"
                    data={chartData}
                    margin={{ top: 4, right: 16, bottom: 0, left: 8 }}
                    barCategoryGap={12}
                  >
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke={CHART_COLORS.grid}
                      horizontal={false}
                    />
                    <XAxis
                      type="number"
                      tick={AXIS_TICK}
                      tickFormatter={(v: number) => formatCount(v)}
                      tickLine={false}
                      axisLine={{ stroke: CHART_COLORS.grid }}
                      allowDecimals={false}
                    />
                    <YAxis
                      type="category"
                      dataKey="label"
                      tick={AXIS_TICK}
                      tickLine={false}
                      axisLine={false}
                      width={120}
                    />
                    <Tooltip
                      cursor={{ fill: CHART_COLORS.primary, fillOpacity: 0.06 }}
                      formatter={(value: number, name: string) => [
                        formatCount(value),
                        name === "used" ? "Used" : "Limit",
                      ]}
                      contentStyle={{
                        background: "hsl(240 6% 10%)",
                        border: `1px solid ${CHART_COLORS.grid}`,
                        borderRadius: 8,
                        fontSize: 12,
                      }}
                    />
                    <Bar dataKey="limit" name="limit" fill={CHART_COLORS.grid} radius={[0, 4, 4, 0]} maxBarSize={18} />
                    <Bar dataKey="used" name="used" radius={[0, 4, 4, 0]} maxBarSize={18}>
                      {chartData.map((entry, index) => (
                        <Cell
                          key={index}
                          fill={
                            entry.over
                              ? CHART_COLORS.destructive
                              : CHART_COLORS.primary
                          }
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            <ul className="space-y-4">
              {metrics.map((metric) => (
                <MeterRow key={metric.metric} metric={metric} />
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}

interface MeterRowProps {
  metric: Readonly<MetricOverage>;
}

/** A single metric's used/limit meter with an overage warning badge. */
function MeterRow({ metric }: Readonly<MeterRowProps>) {
  const bounded = isBounded(metric.limit);
  const percent = metricPercent(metric);
  const used = Math.max(0, metric.used);

  return (
    <li className="space-y-1.5">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="font-medium">{metricLabel(metric.metric)}</span>
        {bounded ? (
          <span className="text-muted-foreground tabular-nums">
            {formatCount(used)} / {formatCount(metric.limit)}
          </span>
        ) : (
          <Badge variant="secondary">
            <InfinityIcon className="size-3" aria-hidden /> Unlimited
          </Badge>
        )}
      </div>
      {bounded && (
        <div className="flex items-center gap-2">
          <Progress
            value={percent}
            aria-label={`${metricLabel(metric.metric)} used`}
            className="flex-1"
          />
          <Badge variant={usageBadgeVariant(metric)} className="shrink-0">
            {metric.overage > 0
              ? `+${formatCount(metric.overage)} over`
              : `${Math.round(percent)}%`}
          </Badge>
        </div>
      )}
    </li>
  );
}
