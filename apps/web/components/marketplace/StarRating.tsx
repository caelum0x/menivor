"use client";

import * as React from "react";
import { Star } from "lucide-react";
import { cn } from "@/lib/utils";
import { RATING_MAX } from "@/lib/types";

export interface StarRatingProps {
  /** Value to render; may be fractional for an average display. */
  value: number;
  /**
   * When provided, the stars become buttons and clicking the nth star calls
   * `onRate(n)`. Omit for a read-only display of `value`.
   */
  onRate?: (stars: number) => void;
  /** Disables interaction (e.g. while a rate request is in flight). */
  disabled?: boolean;
  /** Tailwind size class applied to each star (default "size-4"). */
  size?: string;
  className?: string;
}

/**
 * A 1..{@link RATING_MAX} star widget. Read-only when `onRate` is omitted
 * (fills `Math.round(value)` stars for the aggregate); interactive otherwise,
 * with hover/focus preview. Presentational — the caller owns the rating state.
 */
export function StarRating({
  value,
  onRate,
  disabled = false,
  size = "size-4",
  className,
}: Readonly<StarRatingProps>) {
  const [hover, setHover] = React.useState(0);
  const interactive = typeof onRate === "function";
  const rounded = Math.round(Number.isFinite(value) ? value : 0);

  return (
    <div
      className={cn("flex items-center gap-0.5", className)}
      role={interactive ? "radiogroup" : undefined}
      aria-label={interactive ? "Rate this template" : undefined}
    >
      {Array.from({ length: RATING_MAX }).map((_, index) => {
        const star = index + 1;
        const filled = interactive
          ? star <= (hover || rounded)
          : star <= rounded;
        const icon = (
          <Star
            className={cn(
              size,
              "fill-current",
              filled ? "text-accent" : "text-muted-foreground/30",
            )}
            aria-hidden
          />
        );

        if (!interactive) {
          return <span key={star}>{icon}</span>;
        }

        return (
          <button
            key={star}
            type="button"
            role="radio"
            aria-checked={rounded === star}
            aria-label={`${star} star${star === 1 ? "" : "s"}`}
            disabled={disabled}
            className={cn(
              "rounded-sm transition-transform hover:scale-110",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              "disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:scale-100",
            )}
            onMouseEnter={() => setHover(star)}
            onMouseLeave={() => setHover(0)}
            onFocus={() => setHover(star)}
            onBlur={() => setHover(0)}
            onClick={() => onRate?.(star)}
          >
            {icon}
          </button>
        );
      })}
    </div>
  );
}
