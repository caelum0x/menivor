"use client";

// Reel-create presentation component.

import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";
import { VARIANT_OPTIONS } from "@/components/wizard/types";

interface VariantsSelectorProps {
  value: number;
  onChange: (variants: number) => void;
}

/**
 * Picks how many A/B variations of the reel to generate in one batch (1..N).
 * Each extra variant is a separate job that spends its own credit, so the copy
 * makes the cost implication clear. Emits the chosen count upward.
 */
export function VariantsSelector({ value, onChange }: VariantsSelectorProps) {
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-3">
        {VARIANT_OPTIONS.map((count) => {
          const selected = count === value;
          return (
            <button
              key={count}
              type="button"
              aria-pressed={selected}
              onClick={() => onChange(count)}
              className={cn(
                "relative flex flex-col items-center gap-1 rounded-lg border p-4 text-center transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                selected
                  ? "border-primary ring-2 ring-primary"
                  : "border-border hover:border-primary/60",
              )}
            >
              {selected && (
                <span className="absolute right-2 top-2 flex size-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
                  <Check className="size-3" aria-hidden />
                </span>
              )}
              <span className="flex items-center gap-1.5 text-lg font-semibold">
                {count > 1 && <Copy className="size-4 text-primary" aria-hidden />}
                {count}
              </span>
              <span className="text-xs text-muted-foreground">
                {count === 1
                  ? "Single reel"
                  : `${count} variations`}
              </span>
            </button>
          );
        })}
      </div>
      <p className="text-xs text-muted-foreground">
        {value > 1
          ? `We'll render ${value} independent variations so you can pick the best — each uses one credit.`
          : "Generate a single reel using one credit."}
      </p>
    </div>
  );
}
