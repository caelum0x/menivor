"use client";

import * as React from "react";
import { Film, VolumeX } from "lucide-react";
import type { BrollClip } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export interface BrollClipCardProps {
  clip: BrollClip;
  /** True when this clip is the chosen INTRO. */
  isIntro: boolean;
  /** True when this clip is the chosen OUTRO. */
  isOutro: boolean;
  disabled?: boolean;
  onPick: (role: "intro" | "outro") => void;
}

function formatDuration(seconds?: number): string | null {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) {
    return null;
  }
  return `${Math.round(seconds)}s`;
}

/**
 * A single suggested stock clip: a muted 9:16-ish thumbnail plus two toggle
 * buttons to assign it as the reel's INTRO or OUTRO. Selection is reflected via
 * a highlighted ring + badge; toggling an already-selected role clears it.
 */
export function BrollClipCard({
  clip,
  isIntro,
  isOutro,
  disabled,
  onPick,
}: Readonly<BrollClipCardProps>) {
  const duration = formatDuration(clip.duration);
  const selected = isIntro || isOutro;

  return (
    <div
      className={cn(
        "flex flex-col overflow-hidden rounded-lg border bg-secondary/40",
        selected ? "border-primary ring-1 ring-primary" : "border-border",
      )}
    >
      <div className="relative aspect-video w-full bg-black">
        {clip.thumbnail_url ? (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={clip.thumbnail_url}
            alt={
              clip.search_term
                ? `Stock clip for "${clip.search_term}"`
                : "Suggested stock clip"
            }
            loading="lazy"
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-muted-foreground">
            <Film className="size-6" aria-hidden />
          </div>
        )}

        <span className="absolute left-1.5 top-1.5 inline-flex items-center gap-1 rounded-full bg-background/70 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
          <VolumeX className="size-3" aria-hidden /> Muted
        </span>

        {duration && (
          <span className="absolute bottom-1.5 right-1.5 rounded bg-background/70 px-1.5 py-0.5 text-[10px] font-medium text-foreground">
            {duration}
          </span>
        )}

        {selected && (
          <span className="absolute right-1.5 top-1.5">
            <Badge variant="default">{isIntro ? "Intro" : "Outro"}</Badge>
          </span>
        )}
      </div>

      <div className="flex items-center justify-between gap-2 px-2.5 py-2">
        <span className="truncate text-xs text-muted-foreground">
          {clip.search_term || clip.provider || "Stock clip"}
        </span>
        <span className="flex shrink-0 items-center gap-1">
          <Button
            type="button"
            size="sm"
            variant={isIntro ? "default" : "outline"}
            disabled={disabled}
            aria-pressed={isIntro}
            onClick={() => onPick("intro")}
          >
            Intro
          </Button>
          <Button
            type="button"
            size="sm"
            variant={isOutro ? "default" : "outline"}
            disabled={disabled}
            aria-pressed={isOutro}
            onClick={() => onPick("outro")}
          >
            Outro
          </Button>
        </span>
      </div>
    </div>
  );
}
