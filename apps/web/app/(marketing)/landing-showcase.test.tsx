import { readFileSync } from "node:fs";
import path from "node:path";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ShowcaseTile } from "@/components/marketing/showcase/ShowcaseTile";
import { HeroReel } from "@/components/marketing/showcase/HeroReel";
import { StyleGallery } from "@/components/marketing/styles/StyleGallery";
import { resetSoundFocus } from "@/components/marketing/showcase/soundFocus";
import { allocateStyleGallery, showcaseLayout, showcaseMedia } from "@/lib/styles/showcase";
import { ALL_REEL_STYLES } from "@/lib/styles/catalog";

type Callback = (entries: { isIntersecting: boolean; target: Element }[]) => void;
const observers: { callback: Callback; targets: Element[] }[] = [];

class FakeObserver {
  private readonly entry: { callback: Callback; targets: Element[] };

  constructor(callback: Callback) {
    this.entry = { callback, targets: [] };
    observers.push(this.entry);
  }

  observe(target: Element) {
    this.entry.targets.push(target);
  }

  disconnect() {
    this.entry.targets = [];
  }

  unobserve() {}
}

function intersect(video: Element, isIntersecting = true) {
  act(() => {
    for (const { callback, targets } of observers) {
      if (targets.includes(video)) callback([{ isIntersecting, target: video }]);
    }
  });
}

const [reelA, reelB] = showcaseMedia();

function videoOf(key: string): HTMLVideoElement {
  const video = document.querySelector<HTMLVideoElement>(`video[data-showcase-key="${key}"]`);
  if (!video) throw new Error(`no video for ${key}`);
  return video;
}

beforeEach(() => {
  observers.length = 0;
  resetSoundFocus();
  vi.stubGlobal("IntersectionObserver", FakeObserver);
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("poster-first lazy load (LIVE-QA M-11)", () => {
  it("renders the poster with no video source until the tile is on screen", () => {
    if (!reelA) throw new Error("showcase is empty");
    render(<ShowcaseTile reel={reelA} />);
    const video = videoOf(reelA.key);
    expect(video.getAttribute("poster")).toBe(reelA.poster);
    expect(video.getAttribute("src")).toBeNull();
    expect(video.querySelector("source")).toBeNull();
    intersect(video);
    expect(video.getAttribute("src")).toBe(reelA.mp4);
  });

  it("hero reels attach their loop on view too", () => {
    if (!reelA) throw new Error("showcase is empty");
    render(<HeroReel reel={reelA} priority />);
    const video = videoOf(reelA.key);
    expect(video.getAttribute("src")).toBeNull();
    intersect(video);
    expect(video.getAttribute("src")).toBe(reelA.mp4);
  });

  it("falls back to the same-origin copy when the media domain fails", () => {
    if (!reelA) throw new Error("showcase is empty");
    render(<ShowcaseTile reel={reelA} />);
    const video = videoOf(reelA.key);
    intersect(video);
    fireEvent.error(video);
    expect(video.getAttribute("src")).toBe(reelA.fallbackMp4);
    expect(video.getAttribute("poster")).toBe(reelA.fallbackPoster);
  });
});

describe("tap to unmute, one reel with sound at a time", () => {
  it("plays the full reel with sound and mutes the previous tile", () => {
    if (!reelA || !reelB) throw new Error("showcase needs two reels");
    render(
      <>
        <ShowcaseTile reel={reelA} />
        <ShowcaseTile reel={reelB} />
      </>,
    );
    const a = videoOf(reelA.key);
    const b = videoOf(reelB.key);
    intersect(a);
    intersect(b);
    expect(a.muted && b.muted).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: `Play ${reelA.label}: ${reelA.niche} with sound` }));
    expect(a.getAttribute("src")).toBe(reelA.full);
    expect(a.muted).toBe(false);
    expect(b.muted).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: `Play ${reelB.label}: ${reelB.niche} with sound` }));
    expect(b.getAttribute("src")).toBe(reelB.full);
    expect(b.muted).toBe(false);
    expect(a.muted).toBe(true);
    expect([a, b].filter((v) => !v.muted)).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: `Mute ${reelB.label}: ${reelB.niche}` }));
    expect([a, b].filter((v) => !v.muted)).toHaveLength(0);
  });

  it("gives up the sound when the reel ends or scrolls away", () => {
    if (!reelA) throw new Error("showcase is empty");
    render(<ShowcaseTile reel={reelA} />);
    const a = videoOf(reelA.key);
    intersect(a);
    fireEvent.click(screen.getByRole("button", { name: /with sound/ }));
    expect(a.muted).toBe(false);
    fireEvent.ended(a);
    expect(a.muted).toBe(true);
    expect(a.loop).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /with sound/ }));
    expect(a.muted).toBe(false);
    intersect(a, false);
    fireEvent.pause(a);
    expect(a.muted).toBe(true);
  });

  it("the expanded player takes the sound from every tile", () => {
    if (!reelA || !reelB) throw new Error("showcase needs two reels");
    render(
      <>
        <ShowcaseTile reel={reelA} />
        <ShowcaseTile reel={reelB} />
      </>,
    );
    const a = videoOf(reelA.key);
    intersect(a);
    fireEvent.click(screen.getByRole("button", { name: `Play ${reelA.label}: ${reelA.niche} with sound` }));
    expect(a.muted).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: `Open ${reelB.label}: ${reelB.niche} in the player` }));
    expect(a.muted).toBe(true);
  });
});

describe("no presenter promises while the avatar format is locked (LIVE-QA M-3)", () => {
  const presenterIds = new Set(ALL_REEL_STYLES.filter((s) => s.needsPresenter).map((s) => s.id));

  it("never shows a presenter reel or card", () => {
    const { hero, heroSide, groups } = showcaseLayout();
    const reels = [hero, ...heroSide, ...groups.flatMap((g) => g.reels)];
    expect(reels.some((r) => r.styleId && presenterIds.has(r.styleId))).toBe(false);
    expect(allocateStyleGallery().cards.some((c) => presenterIds.has(c.style.id))).toBe(false);
  });

  it("the gallery links never deep-link a presenter style into /create", () => {
    const { container } = render(<StyleGallery />);
    const hrefs = Array.from(container.querySelectorAll("a")).map((a) => a.getAttribute("href") ?? "");
    for (const id of presenterIds) expect(hrefs.some((h) => h.includes(id))).toBe(false);
  });
});

describe("mobile order (LIVE-QA M-10)", () => {
  it("renders the reel walls after the hero, outside it", () => {
    const source = readFileSync(path.join(__dirname, "page.tsx"), "utf8");
    const hero = source.indexOf("<OneFlowHero");
    const walls = source.indexOf("<ShowcaseWall");
    expect(hero).toBeGreaterThan(-1);
    expect(walls).toBeGreaterThan(hero);
  });
});
