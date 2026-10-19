"use client";

import * as React from "react";
import { ImageOff } from "lucide-react";
import type { WatermarkPosition } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  POSITION_CLASSES,
  PREVIEW_LOGO_WIDTH_FRACTION,
  clampOpacity,
} from "@/components/brand/brand-utils";

interface WatermarkPreviewProps {
  /** Preview URL of the logo (local object URL or presigned), or null. */
  logoUrl: string | null;
  position: WatermarkPosition;
  opacity: number;
  enabled: boolean;
}

/**
 * A live 9:16 sample frame showing exactly where the logo lands on a reel: the
 * chosen corner, at the chosen opacity, sized to the same fraction of the frame
 * width the compose stage uses. When disabled the logo is hidden (the watermark
 * is not applied), matching what the rendered reel would look like.
 */
export function WatermarkPreview({
  logoUrl,
  position,
  opacity,
  enabled,
}: WatermarkPreviewProps) {
  const showLogo = enabled && Boolean(logoUrl);
  return (
    <div className="space-y-3">
      <div
        className="relative mx-auto aspect-[9/16] w-full max-w-[16rem] overflow-hidden rounded-xl border border-border bg-gradient-to-br from-slate-700 via-slate-800 to-slate-900"
        aria-label="Watermark placement preview"
      >
        {/* Faux reel content so the frame reads as a video, not an empty box. */}
        <div className="absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-black/50 to-transparent" />
        <div className="absolute inset-x-4 bottom-6 space-y-2" aria-hidden>
          <div className="h-2.5 w-3/4 rounded-full bg-white/70" />
          <div className="h-2.5 w-1/2 rounded-full bg-white/40" />
        </div>

        {showLogo && logoUrl ? (
          <div
            className={cn("absolute", POSITION_CLASSES[position])}
            style={{
              width: `${PREVIEW_LOGO_WIDTH_FRACTION * 100}%`,
              opacity: clampOpacity(opacity),
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- user logo, local/presigned URL */}
            <img
              src={logoUrl}
              alt="Watermark placement"
              className="h-auto w-full object-contain drop-shadow"
            />
          </div>
        ) : null}
      </div>

      {!logoUrl && (
        <p className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
          <ImageOff className="size-3.5 shrink-0" aria-hidden />
          Upload a logo to preview its placement.
        </p>
      )}
      {logoUrl && !enabled && (
        <p className="text-center text-xs text-muted-foreground">
          Watermark is turned off — it won&apos;t appear on your reels.
        </p>
      )}
    </div>
  );
}
