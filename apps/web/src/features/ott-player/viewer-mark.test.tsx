import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { Player, ViewerMark } from "./Player";
import { MOVE_EVERY_MS, markSpot, untilNextMove } from "./viewer-mark";

vi.mock("media-chrome", () => ({}));
vi.mock("hls.js", () => ({ default: class { static isSupported() { return true; } loadSource() {} attachMedia() {} destroy() {} } }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function grant(body: Record<string, unknown>) {
  const payload = { status: 200, data: body, message: null };
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, statusText: "", headers: new Headers(),
    json: async () => payload, text: async () => JSON.stringify(payload) })));
}

describe("viewer code overlay", () => {
  it("moves on a 30 s beat and stays inside the picture", () => {
    const t = 1_800_000_000_000 - (1_800_000_000_000 % MOVE_EVERY_MS);
    const a = markSpot("AB12CD34", t);
    expect(markSpot("AB12CD34", t + MOVE_EVERY_MS - 1)).toEqual(a);
    const spots = new Set(Array.from({ length: 6 }, (_, n) => JSON.stringify(markSpot("AB12CD34", t + n * MOVE_EVERY_MS))));
    expect(spots.size).toBeGreaterThan(3);
    for (let n = 0; n < 50; n += 1) {
      const s = markSpot("AB12CD34", t + n * MOVE_EVERY_MS);
      expect(s.left).toBeGreaterThanOrEqual(8);
      expect(s.left).toBeLessThan(78);
      expect(s.top).toBeGreaterThanOrEqual(8);
      expect(s.top).toBeLessThan(84);
    }
    expect(untilNextMove(t + 1000)).toBe(MOVE_EVERY_MS - 1000);
  });

  it("re-renders at a new spot after 30 s", () => {
    vi.useFakeTimers();
    let now = 1_800_000_000_000 - (1_800_000_000_000 % MOVE_EVERY_MS);
    const clock = () => now;
    const { container } = render(<ViewerMark mark="AB12CD34" now={clock} />);
    const first = (container.querySelector("[data-viewer-mark]") as HTMLElement).style.cssText;
    let moved = false;
    for (let n = 0; n < 5 && !moved; n += 1) {
      act(() => {
        now += MOVE_EVERY_MS;
        vi.advanceTimersByTime(MOVE_EVERY_MS);
      });
      moved = (container.querySelector("[data-viewer-mark]") as HTMLElement).style.cssText !== first;
    }
    expect(moved).toBe(true);
  });

  it("shows the code on a paid title and nothing on a free one", async () => {
    grant({ manifest_url: "https://api.example/ott/stream/tok/master.m3u8", expires_at: 4102444800, session_id: "s",
      protected: true, viewer_mark: "AB12CD34" });
    const paid = render(<Player titleId="t1" />);
    await waitFor(() => expect(paid.container.querySelector("[data-viewer-mark='AB12CD34']")).toBeTruthy());
    // Inside the media controller, so fullscreen (which takes only the controller) keeps the code.
    expect(paid.container.querySelector("media-controller [data-viewer-mark]")).toBeTruthy();
    cleanup();
    grant({ manifest_url: "https://api.example/ott/stream/tok/master.m3u8", expires_at: 4102444800, session_id: "s",
      protected: false });
    const free = render(<Player titleId="t2" />);
    await new Promise((r) => setTimeout(r, 30));
    expect(free.container.querySelector("[data-viewer-mark]")).toBeNull();
  });
});
