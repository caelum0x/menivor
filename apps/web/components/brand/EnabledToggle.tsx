"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

interface EnabledToggleProps {
  checked: boolean;
  onChange: (enabled: boolean) => void;
  disabled?: boolean;
}

/**
 * A small switch that toggles whether the brand watermark is applied by default.
 * Implemented as a native checkbox-backed `<button role="switch">` so it stays
 * keyboard-accessible without a headless-UI dependency.
 */
export function EnabledToggle({
  checked,
  onChange,
  disabled = false,
}: EnabledToggleProps) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-border bg-secondary/20 p-4">
      <div className="space-y-0.5">
        <p className="text-sm font-medium">Apply watermark by default</p>
        <p className="text-xs text-muted-foreground">
          When on, your logo is overlaid on every new reel. Individual jobs can
          still override or disable it.
        </p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label="Apply watermark by default"
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          "disabled:cursor-not-allowed disabled:opacity-50",
          checked ? "bg-primary" : "bg-input",
        )}
      >
        <span
          className={cn(
            "inline-block size-5 rounded-full bg-background shadow transition-transform",
            checked ? "translate-x-[1.375rem]" : "translate-x-0.5",
          )}
        />
      </button>
    </div>
  );
}
