"use client";

import * as React from "react";
import { X } from "lucide-react";
import { showcaseCredit, type ShowcaseMedia } from "@/lib/styles/showcase";
import { claimSound, releaseSound } from "./soundFocus";

/** Full reel, then the media-domain loop, then the same-origin loop. */
function nextSource(reel: ShowcaseMedia, current: string): string {
  if (current === reel.full) return reel.mp4;
  if (current === reel.mp4) return reel.fallbackMp4;
  return current;
}

/**
 * The expanded reel: a modal `<dialog>` playing the full reel with sound and
 * native controls. Falls back to the muted loop if the full file is missing.
 * While open it holds the page's sound focus, so every tile stays muted.
 * Escape, the close button or a backdrop click closes it.
 */
export function ShowcasePlayer({
  reel,
  onClose,
}: Readonly<{ reel: ShowcaseMedia; onClose: () => void }>) {
  const ref = React.useRef<HTMLDialogElement>(null);
  // No full reel for this key (see SHOWCASE_MISSING_FULL_KEYS): open straight
  // on the muted loop instead of requesting the 404 first.
  const [src, setSrc] = React.useState(reel.full ?? reel.mp4);
  React.useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    // No close() on cleanup: its "close" event would unmount the player
    // right after a dev-mode effect re-run. Unmounting removes the dialog.
    if (!dialog.open) dialog.showModal?.();
  }, []);
  React.useEffect(() => {
    const id = `player:${reel.key}`;
    claimSound(id);
    return () => releaseSound(id);
  }, [reel.key]);
  return (
    <dialog
      ref={ref}
      aria-label={`${reel.label}: ${reel.niche}`}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      className="m-auto w-[min(92vw,420px)] overflow-visible bg-transparent p-0 backdrop:bg-black/80 backdrop:backdrop-blur-sm"
    >
      <div className="relative overflow-hidden rounded-2xl bg-black ring-1 ring-white/10">
        <video
          key={src}
          src={src}
          poster={reel.poster}
          autoPlay
          controls
          playsInline
          onError={() => setSrc((current) => nextSource(reel, current))}
          className="aspect-[9/16] w-full"
        />
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute right-2 top-2 grid size-9 place-items-center rounded-full bg-black/60 text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <p className="mt-3 text-center text-sm text-white/80">
        <span className="font-semibold text-white">{reel.label}</span> · {reel.niche} ·{" "}
        {showcaseCredit(reel)}
      </p>
    </dialog>
  );
}
