import { afterEach, describe, expect, it, vi } from "vitest";
import { parseVast, runPreroll } from "./ads";

const VAST = `<?xml version='1.0' encoding='utf-8'?>
<VAST version="4.2"><Ad id="ad1"><InLine><AdSystem>Menivor</AdSystem><AdTitle>Coffee week</AdTitle>
<Advertiser>Bean Co</Advertiser><Impression id="menivor">https://api.example/api/v1/ott/ads/track/ad1/impression?t=i</Impression>
<Creatives><Creative id="ad1-1" sequence="1"><Linear skipoffset="00:00:05"><Duration>00:00:15</Duration>
<TrackingEvents><Tracking event="start">https://t/start</Tracking><Tracking event="firstQuartile">https://t/q1</Tracking>
<Tracking event="midpoint">https://t/mid</Tracking><Tracking event="thirdQuartile">https://t/q3</Tracking>
<Tracking event="complete">https://t/complete</Tracking><Tracking event="skip">https://t/skip</Tracking></TrackingEvents>
<VideoClicks><ClickThrough>https://bean.example</ClickThrough><ClickTracking>https://t/click</ClickTracking></VideoClicks>
<MediaFiles><MediaFile delivery="progressive" type="video/mp4" width="720" height="1280">https://r2.example/a.mp4</MediaFile></MediaFiles>
</Linear></Creative></Creatives></InLine></Ad></VAST>`;

afterEach(() => vi.restoreAllMocks());

function fakeVideo() {
  const video = document.createElement("video");
  let t = 0;
  Object.defineProperty(video, "currentTime", { get: () => t, set: (v) => { t = v; }, configurable: true });
  Object.defineProperty(video, "duration", { value: 15, configurable: true });
  video.play = vi.fn(async () => undefined);
  return video;
}

describe("VAST", () => {
  it("parses our in-line pre-roll", () => {
    const ad = parseVast(VAST);
    expect(ad).toMatchObject({ id: "ad1", title: "Coffee week", advertiser: "Bean Co", mediaUrl: "https://r2.example/a.mp4",
      durationS: 15, skipAfterS: 5, clickThrough: "https://bean.example" });
  });

  it("treats an empty VAST, a wrapper or a broken document as no ad", () => {
    expect(parseVast(`<VAST version="4.2"/>`)).toBeNull();
    expect(parseVast(`<VAST version="4.2"><Ad><Wrapper><VASTAdTagURI>https://x</VASTAdTagURI></Wrapper></Ad></VAST>`)).toBeNull();
    expect(parseVast("not xml <")).toBeNull();
  });
});

describe("pre-roll", () => {
  it("cannot be skipped before 5 s, fires quartiles once, then hands over to the title", () => {
    const ad = parseVast(VAST)!;
    const video = fakeVideo();
    const sent: string[] = [];
    const countdown: number[] = [];
    const done = vi.fn();
    const ctl = runPreroll(video, ad, { onCountdown: (s) => countdown.push(s), onDone: done, send: (u) => sent.push(u) });
    expect(video.getAttribute("src")).toBe("https://r2.example/a.mp4");
    video.dispatchEvent(new Event("playing"));
    video.currentTime = 2;
    video.dispatchEvent(new Event("timeupdate"));
    expect(ctl.skip()).toBe(false);
    video.currentTime = 8;
    video.dispatchEvent(new Event("timeupdate"));
    video.dispatchEvent(new Event("timeupdate"));
    expect(ctl.click()).toBe("https://bean.example");
    expect(ctl.skip()).toBe(true);
    expect(done).toHaveBeenCalledTimes(1);
    expect(sent).toEqual(["https://api.example/api/v1/ott/ads/track/ad1/impression?t=i", "https://t/start", "https://t/q1",
      "https://t/mid", "https://t/click", "https://t/skip"]);
    expect(countdown.slice(0, 3)).toEqual([5, 3, 0]);
    expect(video.getAttribute("src")).toBeNull();
  });

  it("reports complete when the ad plays to the end", () => {
    const ad = parseVast(VAST)!;
    const video = fakeVideo();
    const sent: string[] = [];
    const done = vi.fn();
    runPreroll(video, ad, { onCountdown: () => undefined, onDone: done, send: (u) => sent.push(u) });
    video.dispatchEvent(new Event("ended"));
    expect(sent).toContain("https://t/complete");
    expect(done).toHaveBeenCalledTimes(1);
  });
});
