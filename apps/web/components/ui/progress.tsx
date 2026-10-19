import * as React from "react";
import { cn } from "@/lib/utils";

export interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Completion percentage, 0..100. Clamped defensively. */
  value?: number;
}

/**
 * Determinate progress bar. Reflects job `progress` (0..100) from the API.
 * Exposes ARIA progressbar semantics for screen readers.
 */
export const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(
  ({ className, value = 0, ...props }, ref) => {
    const clamped = Math.min(100, Math.max(0, Number.isFinite(value) ? value : 0));
    return (
      <div
        ref={ref}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(clamped)}
        className={cn(
          "neu-inset relative h-2 w-full overflow-hidden rounded-full",
          className,
        )}
        {...props}
      >
        <div
          className="h-full rounded-full bg-primary shadow-[0_0_12px_hsl(var(--primary)/0.45)] transition-[width] duration-500 ease-out"
          style={{ width: `${clamped}%` }}
        />
      </div>
    );
  },
);
Progress.displayName = "Progress";
