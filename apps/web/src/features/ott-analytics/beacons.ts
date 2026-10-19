/**
 * First-party QoE beacons (MV12): startup time, watch time, stalls, errors.
 * Only to our own API (`POST /ott/beacons`); no third-party tracker. Events
 * are batched and sent every 15 s and when the page hides.
 */

import { API_BASE } from "@/src/shared/api";

export interface BeaconEvent {
  readonly event: "start" | "heartbeat" | "stall" | "bitrate" | "error" | "end";
  readonly session_id: string;
  readonly title_id: string;
  readonly watched_s?: number;
  readonly startup_ms?: number;
  readonly stall_ms?: number;
  readonly error_code?: string;
  readonly device?: string;
}

export type Send = (events: readonly BeaconEvent[], viewerSession?: string) => void;

export const FLUSH_MS = 15_000;

export const sendBeacons: Send = (events, viewerSession) => {
  if (!events.length) return;
  const route = "/ott/beacons";
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (viewerSession) headers["X-OTT-Viewer"] = viewerSession;
  void fetch(`${API_BASE}${route}`, { method: "POST", keepalive: true, headers, body: JSON.stringify({ events }) })
    .catch(() => undefined);
};

function sessionId(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Watch one video element; returns a stop function that sends the last batch. */
export function trackQuality(
  video: HTMLVideoElement,
  titleId: string,
  opts: { viewerSession?: string; send?: Send; now?: () => number } = {},
): () => void {
  const send = opts.send ?? sendBeacons;
  const now = opts.now ?? (() => performance.now());
  const id = sessionId();
  const queue: BeaconEvent[] = [];
  const base = { session_id: id, title_id: titleId, device: "web" };
  const loadAt = now();
  let started = false;
  let stallAt: number | null = null;
  let lastTime = video.currentTime;
  let watched = 0;
  const flush = () => {
    if (watched > 0) {
      queue.push({ ...base, event: "heartbeat", watched_s: Math.round(watched * 10) / 10 });
      watched = 0;
    }
    send(queue.splice(0), opts.viewerSession);
  };
  const onPlaying = () => {
    if (!started) {
      started = true;
      queue.push({ ...base, event: "start", startup_ms: Math.round(now() - loadAt) });
    }
    if (stallAt !== null) {
      queue.push({ ...base, event: "stall", stall_ms: Math.round(now() - stallAt) });
      stallAt = null;
    }
  };
  const onWaiting = () => {
    if (started && stallAt === null) stallAt = now();
  };
  const onTime = () => {
    const delta = video.currentTime - lastTime;
    if (delta > 0 && delta < 5) watched += delta;
    lastTime = video.currentTime;
  };
  const onError = () => queue.push({ ...base, event: "error", error_code: `media/${video.error?.code ?? 0}` });
  const onEnded = () => {
    queue.push({ ...base, event: "end" });
    flush();
  };
  const onHide = () => {
    if (document.visibilityState === "hidden") flush();
  };
  video.addEventListener("playing", onPlaying);
  video.addEventListener("waiting", onWaiting);
  video.addEventListener("timeupdate", onTime);
  video.addEventListener("error", onError);
  video.addEventListener("ended", onEnded);
  document.addEventListener("visibilitychange", onHide);
  const timer = setInterval(flush, FLUSH_MS);
  return () => {
    clearInterval(timer);
    video.removeEventListener("playing", onPlaying);
    video.removeEventListener("waiting", onWaiting);
    video.removeEventListener("timeupdate", onTime);
    video.removeEventListener("error", onError);
    video.removeEventListener("ended", onEnded);
    document.removeEventListener("visibilitychange", onHide);
    flush();
  };
}
