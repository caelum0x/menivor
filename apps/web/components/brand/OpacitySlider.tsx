"use client";

import * as React from "react";
import { Label } from "@/components/ui/label";
import {
  clampOpacity,
  opacityPercentLabel,
} from "@/components/brand/brand-utils";

interface OpacitySliderProps {
  value: number;
  onChange: (opacity: number) => void;
  disabled?: boolean;
}

/**
 * A native range slider for the watermark opacity (0..1, 5% steps). The current
 * value is echoed as a percentage badge next to the label. Values are clamped to
 * `[0, 1]` before they leave the control.
 */
export function OpacitySlider({
  value,
  onChange,
  disabled = false,
}: OpacitySliderProps) {
  const clamped = clampOpacity(value);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label htmlFor="watermark-opacity">Opacity</Label>
        <span className="text-sm font-medium tabular-nums text-muted-foreground">
          {opacityPercentLabel(clamped)}
        </span>
      </div>
      <input
        id="watermark-opacity"
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={clamped}
        disabled={disabled}
        aria-valuetext={opacityPercentLabel(clamped)}
        onChange={(e) => onChange(clampOpacity(Number(e.target.value)))}
        className="h-2 w-full cursor-pointer appearance-none rounded-full bg-secondary accent-primary disabled:cursor-not-allowed disabled:opacity-50"
      />
    </div>
  );
}
