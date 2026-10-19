"use client";

import * as React from "react";
import type { TooltipProps } from "recharts";

/**
 * A themed Recharts tooltip. Presentational only — Recharts injects `active`,
 * `payload` and `label` at render time. Each row's value is passed through the
 * supplied `format` fn so callers control units (USD / count / duration).
 */
export interface ChartTooltipProps
  extends TooltipProps<number, string> {
  /** Formats a numeric datum for display (e.g. `formatUsd`). */
  format?: (value: number) => string;
  /** Optional label formatter (e.g. prettify a `YYYY-MM-DD` date). */
  labelFormat?: (label: string) => string;
}

export function ChartTooltip({
  active,
  payload,
  label,
  format = (v) => String(v),
  labelFormat,
}: Readonly<ChartTooltipProps>) {
  if (!active || !payload || payload.length === 0) return null;

  const heading =
    typeof label === "string" && labelFormat ? labelFormat(label) : label;

  return (
    <div className="rounded-lg border border-border bg-card/95 px-3 py-2 text-xs shadow-lg backdrop-blur">
      {heading != null ? (
        <p className="mb-1 font-medium text-foreground">{String(heading)}</p>
      ) : null}
      {payload.map((entry, i) => (
        <div
          key={`${entry.name ?? i}`}
          className="flex items-center gap-2 tabular-nums"
        >
          <span
            className="inline-block size-2 shrink-0 rounded-full"
            style={{ backgroundColor: entry.color ?? "currentColor" }}
            aria-hidden
          />
          <span className="text-muted-foreground">{entry.name}</span>
          <span className="ml-auto font-medium text-foreground">
            {typeof entry.value === "number"
              ? format(entry.value)
              : String(entry.value ?? "")}
          </span>
        </div>
      ))}
    </div>
  );
}
