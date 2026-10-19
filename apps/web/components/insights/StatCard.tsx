import * as React from "react";
import type { LucideIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** Accent colour applied to the icon chip; maps to the theme tokens. */
export type StatAccent = "primary" | "accent" | "success" | "destructive";

const ACCENT_CLASSES: Record<StatAccent, string> = {
  primary: "bg-primary/10 text-primary",
  accent: "bg-accent/10 text-accent",
  success: "bg-success/10 text-success",
  destructive: "bg-destructive/10 text-destructive",
};

export interface StatCardProps {
  /** Short metric label, e.g. "Videos generated". */
  label: string;
  /** Preformatted metric value, e.g. "1,204" or "$12.50". */
  value: string;
  /** Optional secondary line under the value. */
  hint?: string;
  /** Optional leading icon. */
  icon?: LucideIcon;
  /** Icon chip accent colour (default "primary"). */
  accent?: StatAccent;
}

/**
 * A single number card for the insights grid. Presentational only — the caller
 * supplies an already-formatted `value`. Props are read-only (no mutation).
 */
export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  accent = "primary",
}: Readonly<StatCardProps>) {
  return (
    <Card>
      <CardContent className="flex items-start justify-between gap-3 p-5">
        <div className="min-w-0">
          <p className="truncate text-sm text-muted-foreground">{label}</p>
          <p className="mt-1 text-2xl font-bold tracking-tight tabular-nums">
            {value}
          </p>
          {hint ? (
            <p className="mt-1 truncate text-xs text-muted-foreground">{hint}</p>
          ) : null}
        </div>
        {Icon ? (
          <span
            className={cn(
              "flex size-9 shrink-0 items-center justify-center rounded-lg",
              ACCENT_CLASSES[accent],
            )}
          >
            <Icon className="size-4" aria-hidden />
          </span>
        ) : null}
      </CardContent>
    </Card>
  );
}
