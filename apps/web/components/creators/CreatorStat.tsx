import type { ComponentType } from "react";
import type { LucideProps } from "lucide-react";
import { cn } from "@/lib/utils";

export interface CreatorStatProps {
  /** Short stat label (e.g. "Followers"). */
  label: string;
  /** Pre-formatted value string. */
  value: string;
  /** Optional Lucide icon rendered before the label. */
  icon?: ComponentType<LucideProps>;
  className?: string;
}

/**
 * A single labelled stat tile used in the profile header. Presentational — the
 * caller owns formatting (see {@link file://./format.ts}).
 */
export function CreatorStat({
  label,
  value,
  icon: Icon,
  className,
}: Readonly<CreatorStatProps>) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-card p-4",
        className,
      )}
    >
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {Icon && <Icon className="size-3.5" aria-hidden />}
        {label}
      </div>
      <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}
