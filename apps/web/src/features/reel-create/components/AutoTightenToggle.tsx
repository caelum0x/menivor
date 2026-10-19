"use client";

// Reel-create presentation component.

import { cn } from "@/lib/utils";

interface AutoTightenToggleProps {
  checked: boolean;
  onChange: (enabled: boolean) => void;
  disabled?: boolean;
}

const HELPER_TOOLTIP =
  "We scan the recording for silent audio gaps and static, low-motion stretches " +
  "and cut them out before rendering — for a tighter, higher-retention reel. " +
  "Your narration and captions are never touched, and if there's no dead air to " +
  "remove your recording is used unchanged.";

/**
 * Review-step switch that opts a job into the auto-tighten retention edit
 * (`auto_tighten`): the raw screen recording is pre-processed to remove dead air
 * (silent/static gaps) before compose. Implemented as a keyboard-accessible
 * `<button role="switch">` mirroring the brand `EnabledToggle`, so it needs no
 * headless-UI dependency. Emits the new value upward; never mutates in place.
 */
export function AutoTightenToggle({
  checked,
  onChange,
  disabled = false,
}: AutoTightenToggleProps) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-border bg-secondary/20 p-4">
      <div className="space-y-0.5">
        <p className="text-sm font-medium" title={HELPER_TOOLTIP}>
          Auto-tighten (remove silent/dead gaps)
        </p>
        <p className="text-xs text-muted-foreground">
          Trim silent and static dead air from your recording before rendering.
          Narration and captions stay in sync; unchanged if nothing to cut.
        </p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label="Auto-tighten (remove silent/dead gaps)"
        title={HELPER_TOOLTIP}
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
