"use client";

// Quick-create presentation component: curated background-footage picker.

import * as React from "react";
import { AlertCircle, Check, Film, RefreshCw } from "lucide-react";
import type { BackgroundClip } from "@/lib/types";
import { ApiError, listBackgrounds } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface BackgroundPickerProps {
  value: string;
  onSelect: (backgroundId: string) => void;
  /** Fired once the catalog loads so the parent can validate its default. */
  onLoaded?: (clips: readonly BackgroundClip[]) => void;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; clips: readonly BackgroundClip[] };

/**
 * The looping footage the reel plays UNDER the karaoke captions when no
 * screen recording is uploaded (`params.background_id`). Only clips whose
 * asset is staged server-side are offered — an unstaged clip can't render.
 */
export function BackgroundPicker({
  value,
  onSelect,
  onLoaded,
}: BackgroundPickerProps) {
  const [state, setState] = React.useState<LoadState>({ status: "loading" });
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    let active = true;
    const controller = new AbortController();
    void (async () => {
      try {
        const clips = await listBackgrounds(undefined, {
          signal: controller.signal,
        });
        if (active) {
          setState({ status: "ready", clips });
          onLoaded?.(clips);
        }
      } catch (err) {
        if (!active || controller.signal.aborted) return;
        setState({
          status: "error",
          message:
            friendlyErrorMessage(err, "Could not load the background library."),
        });
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
  }, [nonce, onLoaded]);

  if (state.status === "loading") {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-20 rounded-lg" />
        ))}
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4">
        <p className="flex items-center gap-2 text-sm text-destructive">
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          {state.message}
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setNonce((n) => n + 1)}
        >
          <RefreshCw className="size-4" aria-hidden /> Try again
        </Button>
      </div>
    );
  }

  const clips = state.clips.filter((clip) => clip.available);

  if (clips.length === 0) {
    return (
      <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm text-muted-foreground">
        No backgrounds are staged yet — your reel will render captions over a
        plain background.
      </p>
    );
  }

  return (
    <div
      role="radiogroup"
      aria-label="Background footage"
      className="grid grid-cols-2 gap-3 sm:grid-cols-3"
    >
      {clips.map((clip) => {
        const selected = clip.id === value;
        return (
          <button
            key={clip.id}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onSelect(clip.id)}
            className={cn(
              "flex flex-col items-start gap-1.5 rounded-lg border border-border p-3 text-left transition-colors",
              selected && "border-primary bg-primary/5",
            )}
          >
            <span className="flex w-full items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-sm font-medium">
                <Film className="size-4 text-muted-foreground" aria-hidden />
                {clip.label || clip.id}
              </span>
              {selected && (
                <Check className="size-4 shrink-0 text-primary" aria-hidden />
              )}
            </span>
            <span className="text-xs capitalize text-muted-foreground">
              {clip.category}
            </span>
          </button>
        );
      })}
    </div>
  );
}
