"use client";

import { cn } from "@/lib/utils";
import { showcaseCredit, type ShowcaseMedia } from "@/lib/styles/showcase";
import { useInViewPlayback } from "./useInViewPlayback";

/**
 * A hero reel: muted, looping, playing while visible. Poster first: the loop
 * is attached only once the reel is on screen, so the poster (preloaded by the
 * page for the lead reel) is the first paint.
 */
export function HeroReel({
  reel,
  priority = false,
  className,
}: Readonly<{ reel: ShowcaseMedia; priority?: boolean; className?: string }>) {
  const { ref } = useInViewPlayback<HTMLVideoElement>({
    src: reel.mp4,
    fallbackSrc: reel.fallbackMp4,
    fallbackPoster: reel.fallbackPoster,
    rootMargin: "0px",
    threshold: 0.05,
  });
  return (
    <div className={cn("overflow-hidden bg-black", className)}>
      <video
        ref={ref}
        muted
        loop
        playsInline
        preload={priority ? "auto" : "none"}
        poster={reel.poster}
        data-showcase-key={reel.key}
        aria-label={`${reel.label}: ${reel.niche}. ${showcaseCredit(reel)}.`}
        className="size-full object-cover"
      />
    </div>
  );
}
