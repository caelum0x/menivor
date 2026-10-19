"use client";

import * as React from "react";
import { attach, protectionLabel, refreshBeforeExpiry, soundFocus, type Attached } from "@menivor/ott-player";
import { ApiError } from "@/src/shared/api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { startPlayback } from "./api";
import { ottAccessLive, ottSurfaceLive } from "./flags";
import { fetchPreroll, runPreroll, type PrerollController } from "./ads";
import { trackQuality } from "@/src/features/ott-analytics/beacons";
import { viewerId } from "./viewer-id";
import { markSpot, untilNextMove } from "./viewer-mark";
import { readSession, resumePosition, startViewerPlayback, trackProgress } from "@/src/features/ott-auth";

/** Our playback refusals (members only, too many screens, not in your country) are written for viewers. */
export function playbackMessage(err: unknown): string {
  if (err instanceof ApiError && [402, 429, 451].includes(err.status) && err.message) {
    return err.message.replace(/\s*\(correlation [^)]*\)$/, "");
  }
  return friendlyErrorMessage(err, "This video could not start.");
}

const loadHls = async () => (await import("hls.js")).default as unknown as import("@menivor/ott-player").HlsConstructor;

/**
 * The OTT web player: hls.js where HLS is not native, media-chrome controls,
 * one sound at a time, tokens refreshed before they expire. Nothing secret is
 * rendered: the grant is fetched after mount.
 */
export function Player({
  titleId,
  poster,
  autoPlay = false,
  handle,
}: Readonly<{ titleId: string; poster?: string; autoPlay?: boolean; handle?: string }>) {
  const video = React.useRef<HTMLVideoElement>(null);
  const [error, setError] = React.useState("");
  const [isProtected, setProtected] = React.useState(false);
  const [mark, setMark] = React.useState("");
  const [adLeft, setAdLeft] = React.useState<number | null>(null);
  const [adLink, setAdLink] = React.useState("");
  const adRef = React.useRef<PrerollController | null>(null);

  React.useEffect(() => {
    void import("media-chrome");
  }, []);

  React.useEffect(() => {
    const el = video.current;
    if (!el) return undefined;
    let attached: Attached | null = null;
    let stopRefresh = () => {};
    let stopTracking = () => {};
    let stopQuality = () => {};
    let cancelled = false;
    const unregister = soundFocus.register(el);
    const load = async (url: string, at = 0) => {
      attached?.destroy();
      attached = await attach(el, url, loadHls, (reason) => setError(`Playback stopped: ${reason}.`));
      if (at > 0) el.currentTime = at;
    };
    void (async () => {
      try {
        const id = viewerId();
        // Wave P PM3.1 (MV6): a signed-in channel viewer plays as that viewer and resumes where they stopped.
        const account = handle ? readSession(handle) : null;
        const play = () => (account ? startViewerPlayback(titleId, id, account.session) : startPlayback(titleId, id));
        const grant = await play();
        if (cancelled) return;
        setProtected(grant.protected);
        setMark(grant.protected ? grant.viewer_mark ?? "" : "");
        const at = account && handle ? await resumePosition(handle, account.session, titleId) : 0;
        // Wave P PM3.2 (MV14): one pre-roll, skippable after 5 s, only where the creator allows ads.
        const ad = ottSurfaceLive("ads") ? await fetchPreroll(titleId, account?.session) : null;
        if (ad && !cancelled) {
          setAdLink(ad.clickThrough);
          await new Promise<void>((resolve) => {
            adRef.current = runPreroll(el, ad, { onCountdown: setAdLeft, onDone: resolve });
          });
          adRef.current = null;
          setAdLeft(null);
        }
        if (cancelled) return;
        // Wave P PM3.5 (MV12): first-party quality beacons (startup, watch time, stalls, errors).
        if (ottSurfaceLive("analytics")) stopQuality = trackQuality(el, titleId, { viewerSession: account?.session });
        await load(grant.manifest_url, at);
        if (account && handle) stopTracking = trackProgress(el, handle, account.session, titleId);
        stopRefresh = refreshBeforeExpiry(grant, play, (next) => {
          const at = el.currentTime;
          const paused = el.paused;
          void load(next.manifest_url, at).then(() => (paused ? undefined : el.play().catch(() => undefined)));
        });
      } catch (err) {
        if (!cancelled) setError(playbackMessage(err));
      }
    })();
    return () => {
      cancelled = true;
      adRef.current?.stop();
      stopRefresh();
      stopTracking();
      stopQuality();
      unregister();
      attached?.destroy();
    };
  }, [titleId, handle]);

  const label = protectionLabel(isProtected, ottAccessLive());
  return (
    <div className="space-y-2">
      <div className="relative">
      <media-controller class="block aspect-[9/16] w-full overflow-hidden rounded-2xl bg-black sm:aspect-video">
        <video ref={video} slot="media" poster={poster} playsInline autoPlay={autoPlay} muted={autoPlay} crossOrigin="anonymous" />
        <media-control-bar>
          <media-play-button />
          <media-time-range />
          <media-time-display showduration />
          <media-mute-button />
          <media-airplay-button />
          <media-pip-button />
          <media-fullscreen-button />
        </media-control-bar>
        {/* Inside the controller so the code stays on screen in fullscreen (QM verify). */}
        {mark ? <ViewerMark mark={mark} /> : null}
      </media-controller>
      </div>
      {adLeft !== null ? (
        <div className="flex items-center gap-3 text-sm" aria-live="polite">
          <span>Ad</span>
          {adLink ? (
            <button type="button" className="underline" onClick={() => {
              const url = adRef.current?.click();
              if (url) window.open(url, "_blank", "noopener,noreferrer");
            }}>Visit sponsor</button>
          ) : null}
          <button type="button" className="rounded-lg border px-2 py-1" disabled={adLeft > 0} onClick={() => adRef.current?.skip()}>
            {adLeft > 0 ? (Number.isFinite(adLeft) ? `Skip in ${adLeft}` : "Ad playing") : "Skip ad"}
          </button>
        </div>
      ) : null}
      {label ? <p className="text-xs text-muted-foreground">{label}</p> : null}
      {error ? <p role="alert" className="text-sm">{error}</p> : null}
    </div>
  );
}

/** The moving viewer code over a paid title (QM1.5): faint, not clickable, moves every 30 s. */
const wallClock = () => Date.now();

export function ViewerMark({ mark, now = wallClock }: Readonly<{ mark: string; now?: () => number }>) {
  const [spot, setSpot] = React.useState(() => markSpot(mark, now()));
  React.useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const move = () => {
      setSpot(markSpot(mark, now()));
      timer = setTimeout(move, untilNextMove(now()));
    };
    timer = setTimeout(move, untilNextMove(now()));
    return () => clearTimeout(timer);
  }, [mark, now]);
  return (
    <span data-viewer-mark={mark} aria-hidden="true"
      className="pointer-events-none absolute select-none font-mono text-xs text-white/40"
      style={{ left: `${spot.left}%`, top: `${spot.top}%` }}>
      {mark}
    </span>
  );
}
