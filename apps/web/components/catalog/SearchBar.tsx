"use client";

import * as React from "react";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  /** Result count shown to the right of the field. */
  resultLabel?: string;
  className?: string;
}

/** Debounce-free controlled search field with a clear button. */
export function SearchBar({
  value,
  onChange,
  placeholder = "Search",
  resultLabel,
  className,
}: Readonly<SearchBarProps>) {
  const inputId = React.useId();
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div className="relative flex-1">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <label htmlFor={inputId} className="sr-only">
          {placeholder}
        </label>
        <input
          id={inputId}
          type="search"
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          className={cn(
            "flex h-10 w-full rounded-md border border-input bg-secondary/40 pl-9 pr-9 text-sm",
            "placeholder:text-muted-foreground",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          )}
        />
        {value && (
          <button
            type="button"
            onClick={() => onChange("")}
            aria-label="Clear search"
            className="absolute right-2 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground"
          >
            <X className="size-4" aria-hidden />
          </button>
        )}
      </div>
      {resultLabel && (
        <span className="shrink-0 text-sm text-muted-foreground">
          {resultLabel}
        </span>
      )}
    </div>
  );
}
