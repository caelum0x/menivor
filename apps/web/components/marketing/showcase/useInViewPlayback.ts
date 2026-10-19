"use client";

import * as React from "react";

export interface LazyVideoOptions {
  /** The muted loop attached on first view. */
  readonly src: string;
  /** Same-origin copy used when `src` fails to load. */
  readonly fallbackSrc?: string;
  readonly fallbackPoster?: string;
  readonly rootMargin?: string;
  readonly threshold?: number;
}

export interface LazyVideo<T extends HTMLVideoElement> {
  readonly ref: React.RefObject<T | null>;
  /** True while the video is on screen. */
  readonly visible: React.RefObject<boolean>;
}

function reducedMotion(): boolean {
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
}

/**
 * Poster first, source on view: the `<video>` renders with only its poster
 * and no `src`, so nothing downloads until it scrolls near the screen. On the
 * first intersection the loop is attached; afterwards it plays while visible
 * and pauses off screen. Never autoplays under reduced motion (the poster
 * stays). If the media domain fails, the same-origin copy takes over.
 */
export function useInViewPlayback<T extends HTMLVideoElement>(options: LazyVideoOptions): LazyVideo<T> {
  const ref = React.useRef<T | null>(null);
  const visible = React.useRef(false);
  const { src, fallbackSrc, fallbackPoster, rootMargin = "160px", threshold = 0.2 } = options;

  React.useEffect(() => {
    const video = ref.current;
    if (!video) return;
    const attach = () => {
      if (!video.getAttribute("src")) video.setAttribute("src", src);
    };
    const play = () => {
      if (reducedMotion()) return;
      video.play()?.catch?.(() => {
        // Autoplay can be refused (data saver, low power); the poster stays.
      });
    };
    const onError = () => {
      const current = video.getAttribute("src") ?? "";
      if (!fallbackSrc || current === fallbackSrc || current !== src) return;
      video.setAttribute("src", fallbackSrc);
      if (fallbackPoster) video.setAttribute("poster", fallbackPoster);
      if (visible.current) play();
    };
    video.addEventListener("error", onError);
    if (typeof IntersectionObserver === "undefined") {
      attach();
      return () => video.removeEventListener("error", onError);
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        visible.current = Boolean(entry?.isIntersecting);
        if (visible.current) {
          attach();
          play();
        } else {
          video.pause();
        }
      },
      { rootMargin, threshold },
    );
    observer.observe(video);
    return () => {
      observer.disconnect();
      video.removeEventListener("error", onError);
    };
  }, [src, fallbackSrc, fallbackPoster, rootMargin, threshold]);

  return { ref, visible };
}
