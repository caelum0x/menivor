"use client";

import * as React from "react";
import { Maximize2, Sparkles, Volume2, VolumeX } from "lucide-react";
import { cn } from "@/lib/utils";
import { showcaseCredit, type ShowcaseMedia } from "@/lib/styles/showcase";
import { useInViewPlayback } from "./useInViewPlayback";
import { ShowcasePlayer } from "./ShowcasePlayer";
import { PasteLinkButton } from "./PasteLinkButton";
import { claimSound, releaseSound, useSoundOwner } from "./soundFocus";

interface ShowcaseTileProps {
  readonly reel: ShowcaseMedia;
  /** Hero tiles load their first frames right away; wall tiles wait. */
  readonly eager?: boolean;
  readonly className?: string;
  /** Tile shape (the wall varies it slightly for its masonry stagger). */
  readonly aspectClass?: string;
}

/** Switches a tile's video to the full reel with sound, inside the tap's gesture. */
function startSound(video: HTMLVideoElement, full: string, key: string): void {
  if (video.getAttribute("src") !== full) {
    video.setAttribute("src", full);
    video.currentTime = 0;
  }
  video.loop = false;
  video.muted = false;
  video.play()?.catch?.(() => {
    // The browser refused sound (rare after a tap): stay muted.
    video.muted = true;
    releaseSound(key);
  });
}

/**
 * One wall tile: a muted 9:16 loop that only plays while on screen (poster
 * first, source attached on view), with the preset name and an honest credit.
 * The speaker button plays the full reel with sound in place; only one reel on
 * the page has sound at a time, so tapping another tile mutes this one. Hover
 * or keyboard focus reveals the name large and a "Paste a link" action that
 * preselects the style; the expand button opens the full reel in a player.
 */
export function ShowcaseTile({
  reel,
  eager = false,
  className,
  aspectClass = "aspect-[9/16]",
}: ShowcaseTileProps) {
  const { ref, visible } = useInViewPlayback<HTMLVideoElement>({
    src: reel.mp4,
    fallbackSrc: reel.fallbackMp4,
    fallbackPoster: reel.fallbackPoster,
  });
  const [open, setOpen] = React.useState(false);
  const owner = useSoundOwner();
  const audible = owner === reel.key;
  const title = `${reel.label}: ${reel.niche}`;

  // Another reel took the sound (or the tile scrolled away): mute, keep moving.
  React.useEffect(() => {
    const video = ref.current;
    if (!video || audible) return;
    video.muted = true;
    video.loop = true;
  }, [audible, ref]);

  React.useEffect(() => {
    const video = ref.current;
    if (!video) return;
    const onEnded = () => {
      releaseSound(reel.key);
      video.muted = true;
      video.loop = true;
      if (visible.current) video.play()?.catch?.(() => undefined);
    };
    const onError = () => {
      // The full reel failed: back to the muted loop, no sound.
      if (video.getAttribute("src") !== reel.full) return;
      releaseSound(reel.key);
      video.setAttribute("src", reel.mp4);
    };
    const onPause = () => {
      if (!visible.current) releaseSound(reel.key);
    };
    video.addEventListener("ended", onEnded);
    video.addEventListener("error", onError);
    video.addEventListener("pause", onPause);
    return () => {
      video.removeEventListener("ended", onEnded);
      video.removeEventListener("error", onError);
      video.removeEventListener("pause", onPause);
    };
  }, [reel.key, reel.full, reel.mp4, ref, visible]);

  const toggleSound = () => {
    const video = ref.current;
    if (!video || !reel.full) return;
    if (audible) {
      video.muted = true;
      video.loop = true;
      releaseSound(reel.key);
      return;
    }
    claimSound(reel.key);
    startSound(video, reel.full, reel.key);
  };

  return (
    <figure
      className={cn(
        "group relative isolate overflow-hidden rounded-2xl bg-black ring-1 ring-white/[0.06]",
        "focus-within:ring-2 focus-within:ring-primary/70",
        className,
      )}
    >
      <div className={cn("relative", aspectClass)}>
        <video
          ref={ref}
          muted
          loop
          playsInline
          preload={eager ? "metadata" : "none"}
          poster={reel.poster}
          data-showcase-key={reel.key}
          aria-label={`${title}. ${showcaseCredit(reel)}.`}
          className="absolute inset-0 size-full object-cover transition-transform duration-700 ease-out group-hover:scale-[1.03]"
        />
        <div
          aria-hidden
          className="absolute inset-0 bg-black/0 transition-colors duration-300 group-focus-within:bg-black/55 group-hover:bg-black/55"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-black/70 to-transparent"
        />
        <span className="pointer-events-none absolute bottom-2.5 left-2.5 max-w-[calc(100%-3.75rem)] truncate rounded-full bg-black/60 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-white/90 backdrop-blur-sm sm:text-[11px]">
          {reel.label}
        </span>
        {reel.full ? (
          <button
            type="button"
            onClick={toggleSound}
            aria-pressed={audible}
            aria-label={audible ? `Mute ${title}` : `Play ${title} with sound`}
            className={cn(
              "absolute right-2 top-2 z-20 grid size-9 place-items-center rounded-full backdrop-blur-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
              audible ? "bg-primary text-primary-foreground" : "bg-black/55 text-white/85 hover:text-white",
            )}
          >
            {audible ? <Volume2 className="size-4" aria-hidden /> : <VolumeX className="size-4" aria-hidden />}
          </button>
        ) : null}
        <button
          type="button"
          onClick={() => {
            const video = ref.current;
            if (video) video.muted = true;
            setOpen(true);
          }}
          aria-label={`Open ${title} in the player`}
          className="absolute bottom-2 right-2 z-10 grid size-8 place-items-center rounded-full bg-black/55 text-white/85 backdrop-blur-sm transition-opacity hover:text-white focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100"
        >
          <Maximize2 className="size-3.5" aria-hidden />
        </button>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3 p-4 text-center opacity-0 transition-opacity duration-300 group-focus-within:opacity-100 group-hover:opacity-100">
          <p className="font-display text-xl font-bold uppercase leading-none tracking-tight text-white sm:text-2xl">
            {reel.label}
          </p>
          <p className="text-xs text-white/75">{reel.niche}</p>
          <PasteLinkButton
            styleId={reel.styleId}
            className="pointer-events-auto"
            icon={<Sparkles className="size-3.5" aria-hidden />}
          />
        </div>
      </div>
      <figcaption className="px-3 pb-2.5 pt-2 text-[11px] leading-snug text-muted-foreground">
        {showcaseCredit(reel)}
      </figcaption>
      {open ? <ShowcasePlayer reel={reel} onClose={() => setOpen(false)} /> : null}
    </figure>
  );
}
