import * as React from "react";
import type { LucideIcon } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatCount } from "./format";

/** A single labelled row rendered as a proportional horizontal bar. */
export interface BreakdownRow {
  /** Display label (already human-readable). */
  readonly label: string;
  /** The bar's count. */
  readonly count: number;
}

export interface CountBreakdownProps {
  /** Card heading, e.g. "By layout". */
  title: string;
  /** Rows to render (rendered in the given order; caller sorts). */
  rows: readonly BreakdownRow[];
  /** Optional heading icon. */
  icon?: LucideIcon;
  /** Bar colour class (default a muted accent). */
  barClassName?: string;
  /** Copy shown when there are no rows. */
  emptyLabel?: string;
  /** Cap the number of rows shown (default: all). */
  maxRows?: number;
}

/**
 * A compact horizontal-bar breakdown — no chart library. Each row is a labelled
 * proportional bar sized against the largest bucket, with the raw count and its
 * share of the total. Reused for layout / language / variants / templates /
 * hooks. Presentational only; props are read-only.
 */
export function CountBreakdown({
  title,
  rows,
  icon: Icon,
  barClassName = "bg-primary",
  emptyLabel = "No data yet.",
  maxRows,
}: Readonly<CountBreakdownProps>) {
  const visible =
    typeof maxRows === "number" ? rows.slice(0, Math.max(0, maxRows)) : rows;
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  const max = rows.reduce((m, row) => Math.max(m, row.count), 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          {Icon ? <Icon className="size-4 text-muted-foreground" aria-hidden /> : null}
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {visible.length === 0 || total === 0 ? (
          <p className="text-sm text-muted-foreground">{emptyLabel}</p>
        ) : (
          <ul className="space-y-3">
            {visible.map((row, index) => {
              const pctOfMax = max > 0 ? (row.count / max) * 100 : 0;
              const pctOfTotal = total > 0 ? (row.count / total) * 100 : 0;
              return (
                <li key={`${row.label}-${index}`}>
                  <div className="mb-1 flex items-center justify-between gap-3 text-sm">
                    <span className="min-w-0 truncate font-medium" title={row.label}>
                      {row.label}
                    </span>
                    <span className="shrink-0 tabular-nums text-muted-foreground">
                      {formatCount(row.count)}
                      <span className="ml-1 text-xs">
                        ({Math.round(pctOfTotal)}%)
                      </span>
                    </span>
                  </div>
                  <div
                    className="h-2 w-full overflow-hidden rounded-full bg-muted"
                    role="img"
                    aria-label={`${row.label}: ${formatCount(row.count)} (${Math.round(
                      pctOfTotal,
                    )}%)`}
                  >
                    <div
                      className={cn("h-full rounded-full transition-all", barClassName)}
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

/** Convert a `{ value: count }` map into descending-sorted breakdown rows. */
export function toBreakdownRows(
  counts: Readonly<Record<string, number>>,
  labelFor: (key: string) => string = (key) => key,
): BreakdownRow[] {
  return Object.entries(counts)
    .map(([key, count]) => ({ label: labelFor(key), count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}
