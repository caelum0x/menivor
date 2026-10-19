"use client";

import * as React from "react";
import { Film } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Jobs-library poster/thumbnail frame, filling its (caller-sized) box. Falls
 * back to a film-strip placeholder when no poster URL is available or the image
 * fails to load. The parent controls dimensions via `className`.
 */

export interface JobPosterProps {
  /** Absolute poster image URL (see `lib/job-media.ts`), or undefined. */
  posterUrl?: string;
  alt?: string;
  /** Sizing/aspect classes for the image (and the placeholder box). */
  className?: string;
}

export function JobPoster({
  posterUrl,
  alt = "Reel poster",
  className,
}: Readonly<JobPosterProps>) {
  const [errored, setErrored] = React.useState(false);

  if (!posterUrl || errored) {
    return (
      <div
        className={cn(
          "flex items-center justify-center bg-secondary text-muted-foreground",
          className,
        )}
      >
        <Film className="size-8" aria-hidden />
      </div>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element -- remote R2 URL; Image opt disabled (next.config).
    <img
      src={posterUrl}
      alt={alt}
      loading="lazy"
      onError={() => setErrored(true)}
      className={cn("object-cover", className)}
    />
  );
}
