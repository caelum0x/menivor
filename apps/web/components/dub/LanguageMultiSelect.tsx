"use client";

import * as React from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import type { DubLanguage } from "@/lib/types";

export interface LanguageMultiSelectProps {
  languages: readonly DubLanguage[];
  /** Currently selected language codes. */
  selected: readonly string[];
  disabled?: boolean;
  onToggle: (code: string) => void;
}

/**
 * Accessible checkbox grid of dubbing target languages. Selection state is owned
 * by the parent; this component only reports toggles. Each row is a native
 * checkbox so keyboard and screen-reader support come for free.
 */
export function LanguageMultiSelect({
  languages,
  selected,
  disabled = false,
  onToggle,
}: Readonly<LanguageMultiSelectProps>) {
  const selectedSet = React.useMemo(
    () => new Set(selected),
    [selected],
  );

  return (
    <ul className="grid gap-2 sm:grid-cols-2" role="group" aria-label="Target languages">
      {languages.map((lang) => {
        const checked = selectedSet.has(lang.code);
        return (
          <li key={lang.code}>
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
                onChange={() => onToggle(lang.code)}
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
              <span className="min-w-0">
                <span className="block truncate font-medium">
                  {lang.native_name || lang.name}
                </span>
                {lang.native_name && lang.native_name !== lang.name && (
                  <span className="block truncate text-xs text-muted-foreground">
                    {lang.name}
                  </span>
                )}
              </span>
              <span className="ml-auto shrink-0 font-mono text-xs uppercase text-muted-foreground">
                {lang.code}
              </span>
            </label>
          </li>
        );
      })}
    </ul>
  );
}
