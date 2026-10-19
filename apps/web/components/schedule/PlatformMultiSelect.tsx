"use client";

import * as React from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import type { PublishPlatform } from "@/lib/types";
import { PLATFORM_OPTIONS } from "@/components/schedule/platforms";

export interface PlatformMultiSelectProps {
  /** Currently selected platform ids. */
  selected: readonly string[];
  disabled?: boolean;
  onToggle: (platform: PublishPlatform) => void;
}

/**
 * Accessible checkbox grid of publish targets. Selection state is owned by the
 * parent; this component only reports toggles. Each row is a native checkbox so
 * keyboard and screen-reader support come for free.
 */
export function PlatformMultiSelect({
  selected,
  disabled = false,
  onToggle,
}: Readonly<PlatformMultiSelectProps>) {
  const selectedSet = React.useMemo(() => new Set(selected), [selected]);

  return (
    <ul
      className="grid gap-2 sm:grid-cols-3"
      role="group"
      aria-label="Publish platforms"
    >
      {PLATFORM_OPTIONS.map(({ id, label, icon: Icon }) => {
        const checked = selectedSet.has(id);
        return (
          <li key={id}>
            <label
              className={cn(
                "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition-colors",
                checked
                  ? "border-primary bg-primary/5"
                  : "border-border hover:bg-secondary/60",
                disabled && "cursor-not-allowed opacity-60",
              )}
            >
              <input
                type="checkbox"
                className="sr-only"
                checked={checked}
                disabled={disabled}
                onChange={() => onToggle(id)}
              />
              <span
                aria-hidden
                className={cn(
                  "flex size-5 shrink-0 items-center justify-center rounded border",
                  checked
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border",
                )}
              >
                {checked && <Check className="size-3.5" />}
              </span>
              <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0 truncate font-medium">{label}</span>
            </label>
          </li>
        );
      })}
    </ul>
  );
}
