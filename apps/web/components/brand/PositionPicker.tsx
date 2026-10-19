"use client";

import * as React from "react";
import { WATERMARK_POSITIONS, type WatermarkPosition } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  POSITION_CLASSES,
  POSITION_LABELS,
} from "@/components/brand/brand-utils";

interface PositionPickerProps {
  value: WatermarkPosition;
  onChange: (position: WatermarkPosition) => void;
  disabled?: boolean;
}

/**
 * A 2x2 grid of corner buttons; each renders a mini 9:16 frame with a dot in the
 * corresponding corner so the choice reads at a glance. The selected corner is
 * highlighted. Fully keyboard-operable via native `<button>`s.
 */
export function PositionPicker({
  value,
  onChange,
  disabled = false,
}: PositionPickerProps) {
  return (
    <div
      role="radiogroup"
      aria-label="Logo position"
      className="grid grid-cols-2 gap-3"
    >
      {WATERMARK_POSITIONS.map((position) => {
        const selected = position === value;
        return (
          <button
            key={position}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={POSITION_LABELS[position]}
            disabled={disabled}
            onClick={() => onChange(position)}
            className={cn(
              "flex items-center gap-3 rounded-lg border p-3 text-left transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              "disabled:cursor-not-allowed disabled:opacity-50",
              selected
                ? "border-primary bg-primary/10"
                : "border-border bg-secondary/20 hover:bg-secondary/40",
            )}
          >
            <span className="relative block h-12 w-7 shrink-0 rounded-sm border border-border bg-background">
              <span
                className={cn(
                  "absolute size-2 rounded-[1px]",
                  POSITION_CLASSES[position],
                  selected ? "bg-primary" : "bg-muted-foreground",
                )}
              />
            </span>
            <span className="text-sm font-medium">
              {POSITION_LABELS[position]}
            </span>
          </button>
        );
      })}
    </div>
  );
}
