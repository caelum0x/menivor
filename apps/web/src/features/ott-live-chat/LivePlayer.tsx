"use client";

import * as React from "react";
import { attach, soundFocus, type Attached } from "@menivor/ott-player";
import { readSession } from "@/src/features/ott-auth";
import { reportLatency, watchLive } from "./api";

const loadHls = async () => (await import("hls.js")).default as unknown as import("@menivor/ott-player").HlsConstructor;
export const LATENCY_EVERY_MS = 30_000;

/** Seconds from capture to screen when the stream carries program dates (Safari), else behind the live edge. */
export function latencySeconds(video: HTMLVideoElement, nowMs = Date.now()): number | null {
  const withDate = video as HTMLVideoElement & { getStartDate?: () => Date };
  const start = withDate.getStartDate?.();
  if (start && !Number.isNaN(start.getTime()) && start.getTime() > 0) {
    return (nowMs - (start.getTime() + video.currentTime * 1000)) / 1000;
  }
  if (video.seekable.length > 0) {
    return video.seekable.end(video.seekable.length - 1) - video.currentTime + 1;
  }
  return null;
}

/** The live player: LL-HLS through our token, latency samples every 30 s (recorded, never promised). */
export function LivePlayer({ handle, streamId }: Readonly<{ handle: string; streamId: string }>) {
  const video = React.useRef<HTMLVideoElement>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    const el = video.current;
    if (!el) return undefined;
    let attached: Attached | null = null;
    let cancelled = false;
    const unregister = soundFocus.register(el);
    const sampler = setInterval(() => {
      const seconds = latencySeconds(el);
      if (seconds !== null && seconds > 0 && seconds < 120 && !el.paused) void reportLatency(streamId, seconds).catch(() => undefined);
    }, LATENCY_EVERY_MS);
    void (async () => {
      try {
        const grant = await watchLive(streamId, readSession(handle)?.session);
        if (cancelled) return;
        attached = await attach(el, grant.hls_url, loadHls, (reason) => setError(`The stream stopped: ${reason}.`));
        await el.play().catch(() => undefined);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "This stream could not start.");
      }
    })();
    return () => {
      cancelled = true;
      clearInterval(sampler);
      unregister();
      attached?.destroy();
    };
  }, [handle, streamId]);

  return (
    <div className="space-y-2">
      <video ref={video} className="aspect-video w-full rounded-2xl bg-black" controls playsInline />
      {error ? <p role="alert" className="text-sm">{error}</p> : null}
    </div>
  );
}
