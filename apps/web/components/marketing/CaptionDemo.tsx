"use client";

import * as React from "react";
import { getPreset } from "@reelforge/caption-engine";

/**
 * Live, 100% honest hero demo: word-by-word karaoke caption highlighting
 * rendered in HTML from the real `hormozi` preset in
 * `@reelforge/caption-engine` — the same registry the API and render worker
 * build ASS subtitles from. No video assets, nothing staged: the colors,
 * casing, and word grouping come straight from the preset.
 *
 * This is the only animated element on the landing page. It pauses (renders a
 * static frame) when the visitor prefers reduced motion.
 */

const PRESET = getPreset("hormozi");

/** The line the demo "captions", split into timed words. */
const WORDS: readonly string[] = [
  "your",
  "screen",
  "recording",
  "becomes",
  "the",
  "reel",
  "every",
  "word",
  "timed",
  "every",
  "beat",
  "captioned",
];

const TICK_MS = 340;

/** Approximate the preset's ASS outline as layered CSS text-shadow. */
function outlineShadow(): string {
  const o = Math.max(1, Math.round(PRESET.outline / 2));
  const hex = PRESET.outline_hex;
  return [
    `-${o}px 0 ${hex}`,
    `${o}px 0 ${hex}`,
    `0 -${o}px ${hex}`,
    `0 ${o}px ${hex}`,
    `${o}px ${o}px ${hex}`,
  ].join(", ");
}

function formatWord(word: string): string {
  return PRESET.uppercase ? word.toUpperCase() : word;
}

export function CaptionDemo() {
  const [active, setActive] = React.useState(0);
  const [animate, setAnimate] = React.useState(false);

  React.useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reduced.matches) return;
    setAnimate(true);
    const timer = window.setInterval(() => {
      setActive((current) => (current + 1) % WORDS.length);
    }, TICK_MS);
    return () => window.clearInterval(timer);
  }, []);

  // Show the group of words containing the active word, exactly like the ASS
  // output groups them (`words_per_group` from the preset).
  const groupSize = PRESET.words_per_group;
  const groupStart = Math.floor(active / groupSize) * groupSize;
  const group = WORDS.slice(groupStart, groupStart + groupSize);

  return (
    <figure className="w-full max-w-sm">
      <div className="glass rounded-[2rem] p-2">
        <div className="relative flex aspect-[9/16] flex-col overflow-hidden rounded-[1.5rem] border border-white/[0.08] bg-black">
          <div className="flex items-center justify-between border-b border-border/60 px-4 py-3">
            <span className="kicker text-muted-foreground">rec 9:16</span>
            <span className="kicker text-primary" aria-hidden>
              {animate ? "live" : "frame"}
            </span>
          </div>

          <div
            className="flex flex-1 items-center justify-center px-6 text-center"
            aria-hidden
          >
            <p
              className="select-none font-display text-4xl font-bold leading-tight"
              style={{ textShadow: outlineShadow() }}
            >
              {group.map((word, index) => {
                const isActive = groupStart + index === active;
                return (
                  <span
                    key={`${groupStart}-${word}-${String(index)}`}
                    style={{
                      color: isActive ? PRESET.highlight_hex : PRESET.primary_hex,
                    }}
                  >
                    {formatWord(word)}
                    {index < group.length - 1 ? " " : ""}
                  </span>
                );
              })}
            </p>
          </div>

          <div className="border-t border-border/60 px-4 py-3">
            <span className="kicker text-muted-foreground">
              preset: hormozi &middot; {PRESET.font}
            </span>
          </div>
        </div>
      </div>
      <figcaption className="kicker mt-3 text-muted-foreground">
        live render of the caption engine&rsquo;s word timing
      </figcaption>
    </figure>
  );
}
