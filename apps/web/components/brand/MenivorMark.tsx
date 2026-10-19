import { useId } from "react";
import { cn } from "@/lib/utils";

/**
 * Menivor brand mark: a circle sliced on the diagonal with the two halves
 * slipped along the cut (an abstract "cut" / motion glyph). Pure geometry on a
 * 64-unit grid; source SVGs live in public/brand/.
 *
 * - `mono` (default) paints with `currentColor` so it follows text colour
 *   (e.g. `text-primary`); the lower half is 55% opacity.
 * - `gradient` uses the calm gold-to-amber brand gradient.
 */

/** Upper-left half, shifted up-right along the cut. */
const UPPER_HALF = "M50.34 10.16A25 25 0 0 0 15.16 45.34Z";
/** Lower-right half, shifted down-left along the cut. */
const LOWER_HALF = "M48.84 18.66A25 25 0 0 1 13.66 53.84Z";

export interface MenivorMarkProps {
  readonly variant?: "mono" | "gradient";
  readonly className?: string;
  /** Accessible name; omit when the mark sits next to the "Menivor" wordmark. */
  readonly title?: string;
}

export function MenivorMark({
  variant = "mono",
  className,
  title,
}: MenivorMarkProps) {
  // useId output contains ":" / "«»", which are unsafe inside url(#...).
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const upperId = `${id}-mv-upper`;
  const lowerId = `${id}-mv-lower`;
  const gradient = variant === "gradient";
  const a11y = title
    ? { role: "img" as const, "aria-label": title }
    : { "aria-hidden": true as const };

  return (
    <svg
      viewBox="0 0 64 64"
      fill="currentColor"
      className={cn("size-5 shrink-0", className)}
      focusable="false"
      {...a11y}
    >
      {gradient && (
        <defs>
          <linearGradient id={upperId} x1="10" y1="8" x2="44" y2="42" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#ffe992" />
            <stop offset="1" stopColor="#ffd83d" />
          </linearGradient>
          <linearGradient id={lowerId} x1="22" y1="22" x2="54" y2="56" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#f0b843" />
            <stop offset="1" stopColor="#c8892e" />
          </linearGradient>
        </defs>
      )}
      <path d={UPPER_HALF} fill={gradient ? `url(#${upperId})` : undefined} />
      <path
        d={LOWER_HALF}
        fill={gradient ? `url(#${lowerId})` : undefined}
        fillOpacity={gradient ? undefined : 0.55}
      />
    </svg>
  );
}
