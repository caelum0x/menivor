import * as React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatCount, formatStateLabel } from "./format";

/** Bar colour per known job-state label; unknown states fall back to muted. */
const STATE_BAR_CLASSES: Record<string, string> = {
  complete: "bg-success",
  failed: "bg-destructive",
  processing: "bg-primary",
};

function barClassFor(state: string): string {
  return STATE_BAR_CLASSES[state.toLowerCase()] ?? "bg-muted-foreground/60";
}

interface StateRow {
  readonly state: string;
  readonly count: number;
}

function toRows(jobsByState: Readonly<Record<string, number>>): StateRow[] {
  return Object.entries(jobsByState)
    .map(([state, count]) => ({ state, count }))
    .sort((a, b) => b.count - a.count);
}

export interface StateBreakdownProps {
  /** Job counts keyed by state label, e.g. `{ complete: 9, failed: 1 }`. */
  jobsByState: Readonly<Record<string, number>>;
}

/**
 * A compact horizontal-bar breakdown of jobs by state. No chart library — each
 * row is a labelled proportional bar sized against the largest bucket.
 */
export function StateBreakdown({ jobsByState }: Readonly<StateBreakdownProps>) {
  const rows = toRows(jobsByState);
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  const max = rows.reduce((m, row) => Math.max(m, row.count), 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Jobs by state</CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 || total === 0 ? (
          <p className="text-sm text-muted-foreground">No jobs yet.</p>
        ) : (
          <ul className="space-y-3">
            {rows.map((row) => {
              const pctOfMax = max > 0 ? (row.count / max) * 100 : 0;
              const pctOfTotal = total > 0 ? (row.count / total) * 100 : 0;
              return (
                <li key={row.state}>
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <span className="font-medium">
                      {formatStateLabel(row.state)}
                    </span>
                    <span className="tabular-nums text-muted-foreground">
                      {formatCount(row.count)}
                      <span className="ml-1 text-xs">
                        ({Math.round(pctOfTotal)}%)
                      </span>
                    </span>
                  </div>
                  <div
                    className="h-2 w-full overflow-hidden rounded-full bg-muted"
                    role="img"
                    aria-label={`${formatStateLabel(row.state)}: ${formatCount(
                      row.count,
                    )} jobs (${Math.round(pctOfTotal)}%)`}
                  >
                    <div
                      className={cn(
                        "h-full rounded-full transition-all",
                        barClassFor(row.state),
                      )}
                      style={{ width: `${Math.max(pctOfMax, 4)}%` }}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
