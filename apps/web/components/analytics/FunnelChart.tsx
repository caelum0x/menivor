import * as React from "react";
import { Filter } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AnalyticsFunnel } from "@/lib/types";
import { cn } from "@/lib/utils";
import { formatCount, formatPct } from "./format";

interface FunnelStep {
  readonly label: string;
  readonly value: number;
  readonly barClassName: string;
  readonly hint: string;
}

export interface FunnelChartProps {
  funnel: Readonly<AnalyticsFunnel>;
}

/**
 * A simple stepped-bar funnel: created -> completed -> published. Each step's
 * width is proportional to the top of the funnel (`created`), with its absolute
 * count and conversion share of `created`. Pure CSS bars — no chart library.
 */
export function FunnelChart({ funnel }: Readonly<FunnelChartProps>) {
  const top = Math.max(funnel.created, 0);
  const steps: FunnelStep[] = [
    {
      label: "Created",
      value: funnel.created,
      barClassName: "bg-primary",
      hint: "Jobs started",
    },
    {
      label: "Completed",
      value: funnel.completed,
      barClassName: "bg-success",
      hint: "Successfully rendered",
    },
    {
      label: "Published",
      value: funnel.published,
      barClassName: "bg-accent",
      hint: "Uploaded to a platform",
    },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Filter className="size-4 text-muted-foreground" aria-hidden />
          Funnel
        </CardTitle>
      </CardHeader>
      <CardContent>
        {top === 0 ? (
          <p className="text-sm text-muted-foreground">
            No jobs created in this window.
          </p>
        ) : (
          <ul className="space-y-4">
            {steps.map((step) => {
              const pct = top > 0 ? step.value / top : 0;
              return (
                <li key={step.label}>
                  <div className="mb-1 flex items-baseline justify-between gap-3">
                    <span className="text-sm font-medium">{step.label}</span>
                    <span className="tabular-nums text-sm text-muted-foreground">
                      {formatCount(step.value)}
                      <span className="ml-1.5 text-xs">{formatPct(pct)}</span>
                    </span>
                  </div>
                  <div
                    className="h-6 w-full overflow-hidden rounded-md bg-muted"
                    role="img"
                    aria-label={`${step.label}: ${formatCount(step.value)} (${formatPct(
                      pct,
                    )} of created)`}
                  >
                    <div
                      className={cn(
                        "flex h-full items-center rounded-md px-2 transition-all",
                        step.barClassName,
                      )}
                      style={{ width: `${Math.max(pct * 100, 3)}%` }}
                    />
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{step.hint}</p>
                </li>
              );
            })}
          </ul>
        )}
        {funnel.failed > 0 ? (
          <p className="mt-4 text-xs text-muted-foreground">
            <span className="font-medium text-destructive">
              {formatCount(funnel.failed)}
            </span>{" "}
            job{funnel.failed === 1 ? "" : "s"} failed in this window.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
