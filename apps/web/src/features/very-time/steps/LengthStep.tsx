"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

import type { VeryTimeDuration } from "../api";
import { DURATIONS } from "../model";

/** Step 3: three cards. One tap picks the length and moves on (15 seconds is preselected). */
export function LengthStep({
  value,
  onPick,
}: Readonly<{ value: VeryTimeDuration; onPick: (seconds: VeryTimeDuration) => void }>) {
  return (
    <ul className="grid gap-3 sm:grid-cols-3" aria-label="Lengths">
      {DURATIONS.map((option) => {
        const selected = value === option.seconds;
        return (
          <li key={option.seconds}>
            <button
              type="button"
              aria-pressed={selected}
              onClick={() => onPick(option.seconds)}
              className={cn(
                "glass-subtle flex h-full w-full flex-col items-start gap-2 rounded-2xl p-5 text-left transition-colors",
                "hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                selected && "border-primary/70",
              )}
            >
              <span className="text-base font-semibold tabular-nums">{option.title}</span>
              <span className="text-sm text-muted-foreground">{option.description}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
