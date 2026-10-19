"use client";

// Reel-create presentation component.

import { Check } from "lucide-react";
import type { Layout } from "@/lib/types";
import { cn } from "@/lib/utils";
import { LAYOUT_OPTIONS } from "@/components/wizard/types";
import { lockedOptionReason, type LockedFormat } from "@/src/shared/launch";

interface LayoutPickerProps {
  value: Layout;
  onSelect: (layout: Layout) => void;
  /**
   * Set when the server cannot render AI avatar reels. Every layout here
   * composites a presenter, so all options are disabled with the reason.
   */
  avatarLock?: LockedFormat | null;
}

/** Small 9:16 diagram illustrating how the presenter sits over the screen. */
function LayoutDiagram({ layout }: { layout: Layout }) {
  return (
    <div className="relative mx-auto aspect-[9/16] w-16 overflow-hidden rounded-md border border-border bg-secondary">
      {/* screen recording base */}
      <div className="absolute inset-0 bg-gradient-to-br from-secondary to-muted" />

      {layout === "pip" && (
        <span className="absolute bottom-1.5 right-1.5 size-5 rounded-full border-2 border-background bg-primary" />
      )}
      {layout === "hook_intro" && (
        <span className="absolute inset-x-0 top-0 flex h-1/2 items-center justify-center bg-primary/80 text-[8px] font-bold text-primary-foreground">
          HOOK
        </span>
      )}
      {layout === "split" && (
        <span className="absolute inset-x-0 top-0 h-1/2 border-b-2 border-background bg-primary/70" />
      )}
    </div>
  );
}

/**
 * Visual cards for choosing how the presenter is composited over the screen
 * recording: picture-in-picture, hook intro, or split screen.
 */
export function LayoutPicker({ value, onSelect, avatarLock = null }: LayoutPickerProps) {
  const lockedReason = avatarLock ? lockedOptionReason(avatarLock) : "";
  return (
    <ul className="grid gap-3 sm:grid-cols-3">
      {LAYOUT_OPTIONS.map((option) => {
        const selected = option.value === value && !avatarLock;
        return (
          <li key={option.value}>
            <button
              type="button"
              aria-pressed={selected}
              disabled={avatarLock !== null}
              title={lockedReason || undefined}
              onClick={() => onSelect(option.value)}
              className={cn(
                "relative flex h-full w-full flex-col items-center gap-3 rounded-lg border p-4 text-center transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                "disabled:cursor-not-allowed disabled:opacity-50",
                selected
                  ? "border-primary ring-2 ring-primary"
                  : "border-border hover:border-primary/60",
              )}
            >
              {selected && (
                <span className="absolute right-2 top-2 flex size-6 items-center justify-center rounded-full bg-primary text-primary-foreground">
                  <Check className="size-4" aria-hidden />
                </span>
              )}
              <LayoutDiagram layout={option.value} />
              <span>
                <span className="block text-sm font-medium">{option.title}</span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {option.description}
                </span>
                {lockedReason && (
                  <span className="mt-1 block text-xs font-medium text-muted-foreground">
                    {lockedReason}
                  </span>
                )}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
