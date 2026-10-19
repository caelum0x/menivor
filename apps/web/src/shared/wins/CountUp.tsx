"use client";

import * as React from "react";
import { useReducedMotion } from "./use-reduced-motion";

interface CountUpProps {
  readonly value: number;
  /** Appended after the number, e.g. "+" for a floor. */
  readonly suffix?: string;
  readonly durationMs?: number;
  readonly className?: string;
}

/**
 * A real number that ticks up from where it was to where it is. Jumps
 * straight to the value under prefers-reduced-motion.
 */
export function CountUp({ value, suffix = "", durationMs = 900, className }: CountUpProps) {
  const reduced = useReducedMotion();
  const [shown, setShown] = React.useState(reduced ? value : 0);
  const fromRef = React.useRef(0);

  React.useEffect(() => {
    if (reduced) {
      setShown(value);
      fromRef.current = value;
      return;
    }
    const from = fromRef.current;
    const start = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(Math.round(from + (value - from) * eased));
      if (t < 1) frame = requestAnimationFrame(step);
      else fromRef.current = value;
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value, reduced, durationMs]);

  return (
    <span className={className} aria-label={`${value}${suffix}`}>
      <span aria-hidden className="tabular-nums">
        {shown.toLocaleString()}
        {suffix}
      </span>
    </span>
  );
}
