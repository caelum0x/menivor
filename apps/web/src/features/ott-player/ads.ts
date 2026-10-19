/**
 * Pre-roll ads (MV14): our own VAST 4.2 only (no wrappers, no third-party
 * demand). The ad plays in the same video element before the title; it can be
 * skipped after the VAST skip offset (5 s); tracking pixels are fired with
 * `keepalive` and never block playback.
 */

import { API_BASE } from "@/src/shared/api";

export type TrackingEvent = "start" | "firstQuartile" | "midpoint" | "thirdQuartile" | "complete" | "skip";

export interface VastAd {
  readonly id: string;
  readonly title: string;
  readonly advertiser: string;
  readonly mediaUrl: string;
  readonly durationS: number;
  readonly skipAfterS: number;
  readonly impressions: readonly string[];
  readonly tracking: Readonly<Partial<Record<TrackingEvent, readonly string[]>>>;
  readonly clickThrough: string;
  readonly clickTracking: readonly string[];
}

function seconds(hms: string | null | undefined): number {
  const match = /^(\d+):(\d{2}):(\d{2})(?:\.(\d+))?$/.exec((hms ?? "").trim());
  if (!match) return 0;
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]) + Number(`0.${match[4] ?? "0"}`);
}

const text = (el: Element | null | undefined) => (el?.textContent ?? "").trim();

/** The first linear in-line ad of a VAST document, or null for "no ad" (wrappers are ignored). */
export function parseVast(xml: string): VastAd | null {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  if (doc.getElementsByTagName("parsererror").length) return null;
  const ad = doc.querySelector("VAST > Ad");
  const inline = ad?.querySelector("InLine");
  const linear = inline?.querySelector("Linear");
  const media = Array.from(linear?.querySelectorAll("MediaFile") ?? []).find(
    (m) => m.getAttribute("type") === "video/mp4" && text(m).startsWith("https://"),
  );
  if (!ad || !inline || !linear || !media) return null;
  const tracking: Partial<Record<TrackingEvent, string[]>> = {};
  for (const t of Array.from(linear.querySelectorAll("TrackingEvents > Tracking"))) {
    const event = t.getAttribute("event") as TrackingEvent | null;
    if (event) (tracking[event] ??= []).push(text(t));
  }
  const skip = linear.getAttribute("skipoffset");
  return {
    id: ad.getAttribute("id") ?? "",
    title: text(inline.querySelector("AdTitle")),
    advertiser: text(inline.querySelector("Advertiser")),
    mediaUrl: text(media),
    durationS: seconds(text(linear.querySelector("Duration"))),
    skipAfterS: skip ? seconds(skip) : Number.POSITIVE_INFINITY,
    impressions: Array.from(inline.querySelectorAll("Impression")).map(text).filter(Boolean),
    tracking,
    clickThrough: text(linear.querySelector("VideoClicks > ClickThrough")),
    clickTracking: Array.from(linear.querySelectorAll("VideoClicks > ClickTracking")).map(text).filter(Boolean),
  };
}

export function ping(url: string): void {
  if (!url) return;
  void fetch(url, { method: "GET", keepalive: true, mode: "no-cors", cache: "no-store" }).catch(() => undefined);
}

/** Ask our ad decision for this play; any failure means "no ad" (the title always starts). */
export async function fetchPreroll(titleId: string, viewerSession?: string): Promise<VastAd | null> {
  try {
    const tid = encodeURIComponent(titleId);
    const route = `/ott/ads/vast/${tid}`;
    const response = await fetch(`${API_BASE}${route}`, {
      headers: viewerSession ? { "X-OTT-Viewer": viewerSession } : {},
      cache: "no-store",
    });
    if (!response.ok) return null;
    return parseVast(await response.text());
  } catch {
    return null;
  }
}

export interface PrerollHandlers {
  /** Seconds left before the ad can be skipped (0 = skippable now). */
  readonly onCountdown: (secondsLeft: number) => void;
  readonly onDone: () => void;
  readonly send?: (url: string) => void;
}

export interface PrerollController {
  skip(): boolean;
  click(): string;
  stop(): void;
}

export function runPreroll(video: HTMLVideoElement, ad: VastAd, handlers: PrerollHandlers): PrerollController {
  const send = handlers.send ?? ping;
  const fired = new Set<string>();
  let done = false;
  const fire = (event: TrackingEvent) => {
    if (fired.has(event)) return;
    fired.add(event);
    for (const url of ad.tracking[event] ?? []) send(url);
  };
  const finish = () => {
    if (done) return;
    done = true;
    video.removeEventListener("playing", onPlaying);
    video.removeEventListener("timeupdate", onTime);
    video.removeEventListener("ended", onEnded);
    video.removeEventListener("error", onError);
    video.removeAttribute("src");
    handlers.onDone();
  };
  const onPlaying = () => {
    if (fired.has("impression")) return;
    fired.add("impression");
    for (const url of ad.impressions) send(url);
    fire("start");
  };
  const onTime = () => {
    const duration = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : ad.durationS;
    const at = video.currentTime;
    if (duration > 0) {
      if (at >= duration * 0.25) fire("firstQuartile");
      if (at >= duration * 0.5) fire("midpoint");
      if (at >= duration * 0.75) fire("thirdQuartile");
    }
    handlers.onCountdown(Math.max(0, Math.ceil(ad.skipAfterS - at)));
  };
  const onEnded = () => {
    fire("complete");
    finish();
  };
  const onError = () => finish();
  video.addEventListener("playing", onPlaying);
  video.addEventListener("timeupdate", onTime);
  video.addEventListener("ended", onEnded);
  video.addEventListener("error", onError);
  handlers.onCountdown(Number.isFinite(ad.skipAfterS) ? Math.ceil(ad.skipAfterS) : Number.POSITIVE_INFINITY);
  video.src = ad.mediaUrl;
  void video.play().catch(() => finish());
  return {
    skip() {
      if (done || video.currentTime < ad.skipAfterS) return false;
      fire("skip");
      finish();
      return true;
    },
    click() {
      for (const url of ad.clickTracking) send(url);
      return ad.clickThrough;
    },
    stop: finish,
  };
}
