import { cn } from "@/lib/utils";

interface WinCheckProps {
  readonly size?: number;
  readonly className?: string;
}

/** A clean check that draws itself once (static under reduced motion). */
export function WinCheck({ size = 40, className }: WinCheckProps) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full bg-primary/15 motion-safe:animate-pop-in",
        className,
      )}
      style={{ width: size, height: size }}
      aria-hidden
    >
      <svg viewBox="0 0 24 24" width={size * 0.55} height={size * 0.55} fill="none">
        <path
          d="M5 12.5l4.5 4.5L19 7.5"
          stroke="currentColor"
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          pathLength={1}
          strokeDasharray={1}
          className="text-primary motion-safe:animate-draw-check"
        />
      </svg>
    </span>
  );
}
