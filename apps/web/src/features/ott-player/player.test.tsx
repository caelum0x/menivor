import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { SoundFocus, attach, protectionLabel, refreshBeforeExpiry, type HlsConstructor } from "@menivor/ott-player";
import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";
import { Storefront } from "./Storefront";
import { handleForHost, isCustomHost, rewritePath } from "./custom-domain";
import { Player } from "./Player";

vi.mock("media-chrome", () => ({}));
vi.mock("hls.js", () => ({ default: class { static isSupported() { return true; } loadSource() {} attachMedia() {} destroy() {} } }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function fakeVideo(native: boolean) {
  const video = document.createElement("video");
  video.canPlayType = () => (native ? "maybe" : "");
  return video;
}

describe("player core", () => {
  it("plays HLS natively where it can and loads hls.js only otherwise", async () => {
    const native = fakeVideo(true);
    const loadHls = vi.fn();
    const a = await attach(native, "https://api/stream/t/master.m3u8", loadHls);
    expect(a.engine).toBe("native");
    expect(native.src).toBe("https://api/stream/t/master.m3u8");
    expect(loadHls).not.toHaveBeenCalled();
    const calls: string[] = [];
    class FakeHls {
      static isSupported() { return true; }
      loadSource(url: string) { calls.push(`load:${url}`); }
      attachMedia() { calls.push("attach"); }
      destroy() { calls.push("destroy"); }
    }
    const b = await attach(fakeVideo(false), "https://api/x.m3u8", async () => FakeHls as unknown as HlsConstructor);
    b.destroy();
    expect(b.engine).toBe("hls.js");
    expect(calls).toEqual(["load:https://api/x.m3u8", "attach", "destroy"]);
  });

  it("keeps one sound at a time", () => {
    const focus = new SoundFocus();
    const a = document.createElement("video");
    const b = document.createElement("video");
    focus.register(a);
    focus.register(b);
    a.muted = false;
    b.muted = false;
    a.dispatchEvent(new Event("volumechange"));
    expect(b.muted).toBe(true);
    expect(a.muted).toBe(false);
  });

  it("refreshes the playback grant before it expires", async () => {
    let scheduled: (() => void) | null = null;
    let waitMs = 0;
    const applied: string[] = [];
    const stop = refreshBeforeExpiry(
      { manifest_url: "a", expires_at: 1600, session_id: "s", protected: false },
      async () => ({ manifest_url: "b", expires_at: 2200, session_id: "s", protected: false }),
      (next) => applied.push(next.manifest_url),
      { now: () => 1000, leadSeconds: 60, schedule: (fn, ms) => { scheduled = fn; waitMs = ms; return 1; }, cancel: () => {} },
    );
    expect(waitMs).toBe(540_000);
    await (scheduled as unknown as () => Promise<void>)();
    expect(applied).toEqual(["b"]);
    stop();
  });

  it("says protected streaming only where tier 1 is live, never DRM", () => {
    expect(protectionLabel(true, true)).toBe("Protected streaming");
    expect(protectionLabel(true, false)).toBe("");
    expect(protectionLabel(false, true)).toBe("");
  });
});

describe("Player", () => {
  it("renders no token or manifest into the page HTML", () => {
    const html = renderToString(<Player titleId="t1" poster="https://art/p.jpg" />);
    expect(html).not.toMatch(/stream\/|m3u8|token|\?t=/);
  });

  it("fetches the grant after mount and shows a plain refusal", async () => {
    const payload = { status: 429, data: { code: "too_many_streams" }, message: "You are already watching on 2 screens. Stop one to watch here." };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 429, statusText: "", headers: new Headers(),
      json: async () => payload, text: async () => JSON.stringify(payload) })));
    render(<Player titleId="t1" />);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/already watching on 2 screens/));
  });
});

const CARD = { id: "t1", title: "Episode one", synopsis: "", kind: "episode" as const, artwork_url: "", duration_s: 60,
  genres: [], rating: "", series_id: "s1", season: 1, episode: 1, access_tier: "free" as const, available_here: false };

describe("storefront", () => {
  it("renders grid, rails and course layouts and marks titles not available here", () => {
    const base = { handle: "maya", title: "Maya", tagline: "Films", brand_colors: ["#112233"], titles: [CARD],
      rails: [{ id: "r1", title: "Start here", items: [CARD] }], series: [{ id: "s1", title: "Season one", synopsis: "", episodes: [CARD] }] };
    const { rerender } = render(<Storefront data={{ ...base, layout: "grid" }} />);
    expect(screen.getByText("Not available in your country")).toBeTruthy();
    rerender(<Storefront data={{ ...base, layout: "rails" }} />);
    expect(screen.getByRole("region", { name: "Start here" })).toBeTruthy();
    rerender(<Storefront data={{ ...base, layout: "course" }} />);
    expect(screen.getByRole("link", { name: "1. Episode one" }).getAttribute("href")).toBe("/c/maya/t1");
  });
});

describe("custom domains", () => {
  it("rewrites only foreign hosts, cached per host", async () => {
    expect(isCustomHost("menivor.com")).toBe(false);
    expect(isCustomHost("app.menivor.com")).toBe(false);
    expect(isCustomHost("watch.maya.example:443")).toBe(true);
    const lookup = vi.fn(async () => ({ handle: "maya" }));
    expect(await handleForHost("watch.maya.example", lookup, 1)).toBe("maya");
    expect(await handleForHost("watch.maya.example", lookup, 2)).toBe("maya");
    expect(lookup).toHaveBeenCalledTimes(1);
    expect(rewritePath("maya", "/")).toBe("/c/maya");
    expect(rewritePath("maya", "/t1")).toBe("/c/maya/t1");
  });
});

describe("copy", () => {
  it("passes the copy denylist and never says DRM", () => {
    const web = process.cwd();
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const files = ["src/features/ott-player/Player.tsx", "src/features/ott-player/Storefront.tsx",
      "app/(ott)/c/[handle]/page.tsx", "app/(ott)/c/[handle]/[titleId]/page.tsx", "app/(ott)/embed/[id]/page.tsx"];
    const units = files.flatMap((rel) => sourceUnits(fs.readFileSync(path.join(web, rel), "utf8"), rel).units);
    expect(checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error")).toEqual([]);
    for (const rel of files) expect(fs.readFileSync(path.join(web, rel), "utf8")).not.toMatch(/\bDRM\b/);
  });
});
