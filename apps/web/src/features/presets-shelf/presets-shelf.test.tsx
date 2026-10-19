import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const signed = { isLoaded: true, isSignedIn: true };
vi.mock("@/lib/auth-state", () => ({ useSignedInState: () => signed }));
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => async () => "session" }));

import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";
import { formatSeconds, type PresetTile } from "./api";
import { PresetShelf } from "./PresetShelf";
import { PresetUse } from "./PresetUse";

const FILTER: PresetTile = {
  id: "crash-zoom",
  name: "Crash zoom",
  blurb: "A fast punch toward your subject on the hook.",
  kind: "filter",
  credit_kind: "standard",
  credit_label: "Standard credits",
  inputs: ["subject"],
  preview: { loop_url: "https://media.example/presets/crash-zoom.mp4", poster_url: "https://media.example/presets/crash-zoom.jpg" },
  create_url: "/presets-gallery?use=crash-zoom",
  target_seconds: 180,
};
const MODEL: PresetTile = { ...FILTER, id: "melt-away", name: "Melt away", kind: "model", credit_kind: "ai_video",
  credit_label: "AI-video credits", inputs: ["subject", "image"], target_seconds: 120 };

type Route = (url: string, body: unknown) => { status: number; data: unknown };

function stubApi(route: Route) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method: init?.method ?? "GET", body });
      const { status, data } = route(url, body);
      const payload = { status, data, message: status === 200 ? "" : "refused" };
      return {
        ok: status === 200, status, statusText: "", headers: new Headers(),
        json: async () => payload, text: async () => JSON.stringify(payload),
      };
    }),
  );
  return calls;
}

beforeEach(() => {
  signed.isSignedIn = true;
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("preset shelf", () => {
  it("shows moving preview loops that open the preset", () => {
    render(<PresetShelf initialTiles={[FILTER]} />);
    const link = screen.getByRole("link", { name: /Crash zoom/ });
    expect(link.getAttribute("href")).toBe("/presets-gallery?use=crash-zoom");
    const video = screen.getByLabelText("Crash zoom preview") as HTMLVideoElement;
    expect(video.getAttribute("src")).toBe(FILTER.preview.loop_url);
    expect(video.muted).toBe(true);
    expect(video.hasAttribute("loop")).toBe(true);
  });

  it("loads the public shelf without a token and shows no placeholder tiles", async () => {
    const calls = stubApi(() => ({ status: 200, data: { presets: [] } }));
    render(<PresetShelf />);
    expect(await screen.findByText(/New presets are on the way/)).toBeTruthy();
    expect(calls[0]?.url).toMatch(/\/presets\/shelf$/);
    expect(document.querySelectorAll("video")).toHaveLength(0);
  });

  it("names no vendor or model in rendered HTML", () => {
    const web = path.resolve(__dirname, "../../..");
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    render(<PresetShelf initialTiles={[FILTER, MODEL]} />);
    const html = document.body.innerHTML;
    expect(html).not.toMatch(/kling|veo|seedance|hailuo|runway|wan-?2|fal\.ai|replicate|comfyui|elevenlabs/i);
    const units = ["PresetShelf.tsx", "PresetUse.tsx"].flatMap(
      (rel) => sourceUnits(fs.readFileSync(path.join(__dirname, rel), "utf8"), `src/features/presets-shelf/${rel}`).units,
    );
    const page = path.resolve(web, "app/(marketing)/presets-gallery/page.tsx");
    units.push(...sourceUnits(fs.readFileSync(page, "utf8"), "app/(marketing)/presets-gallery/page.tsx").units);
    const hits = checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error");
    expect(hits).toEqual([]);
  });
});

describe("preset use", () => {
  it("prices first, then makes it through /jobs and measures tap to first result", async () => {
    const calls = stubApi((url) => {
      if (url.endsWith("/presets/shelf/crash-zoom/plan")) {
        return { status: 200, data: { route: "jobs", preset_id: "crash-zoom", body: { params: { camera_motion: "crash_zoom_in" }, variants: 1 } } };
      }
      if (url.endsWith("/jobs/quote")) return { status: 200, data: { total: { standard: 1 }, affordable: true } };
      if (url.endsWith("/jobs")) return { status: 200, data: { job_id: "job123" } };
      if (url.endsWith("/presets/shelf/crash-zoom/runs")) return { status: 200, data: { job_id: "job123" } };
      if (url.endsWith("/presets/runs/job123")) {
        return { status: 200, data: { job_id: "job123", preset_id: "crash-zoom", seconds_to_result: 134, target_seconds: 180, within_target: true } };
      }
      return { status: 404, data: {} };
    });
    const opened = new Date("2026-09-30T10:00:00.000Z");
    render(<PresetUse presetId="crash-zoom" initialTile={FILTER} now={() => opened} />);
    fireEvent.change(screen.getByLabelText("Your topic or link"), { target: { value: "Fresh pasta class" } });
    fireEvent.click(screen.getByRole("button", { name: /See the price/ }));
    expect((await screen.findByTestId("preset-price")).textContent).toBe("Uses 1 credit.");
    expect(calls.some((c) => c.url.endsWith("/jobs"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /Make it/ }));
    expect((await screen.findByTestId("preset-timing")).textContent).toBe("First result in 2 min 14 s (target 3 min 0 s).");
    const run = calls.find((c) => c.url.endsWith("/presets/shelf/crash-zoom/runs"));
    expect(run?.body).toEqual({ job_id: "job123", opened_at: opened.toISOString() });
    const job = calls.find((c) => c.url.endsWith("/jobs"));
    expect(job?.body).toEqual({ params: { camera_motion: "crash_zoom_in" }, variants: 1 });
    expect(screen.getByRole("link", { name: "Open the result" }).getAttribute("href")).toBe("/jobs/job123");
  });

  it("sends a signed-out visitor to sign up and back to this preset", () => {
    signed.isSignedIn = false;
    stubApi(() => ({ status: 200, data: {} }));
    render(<PresetUse presetId="crash-zoom" initialTile={FILTER} />);
    const link = screen.getByRole("link", { name: /Sign up with your email/ });
    expect(decodeURIComponent(link.getAttribute("href") ?? "")).toContain("/presets-gallery?use=crash-zoom");
  });

  it("asks for an image before an animate-image preset can be priced", () => {
    stubApi(() => ({ status: 200, data: {} }));
    render(<PresetUse presetId="melt-away" initialTile={MODEL} />);
    fireEvent.change(screen.getByLabelText("Your topic or link"), { target: { value: "ice cream" } });
    expect(screen.getByText(/animates your own image/)).toBeTruthy();
    expect((screen.getByRole("button", { name: /See the price/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("prices a model preset in AI-video credits via the preset quote", async () => {
    const calls = stubApi((url) => {
      if (url.endsWith("/plan")) return { status: 200, data: { route: "generation/broll/generate", preset_id: "melt-away", body: { prompt: "p", mode: "i2v", image_key: "k" } } };
      if (url.endsWith("/jobs/quote/preset")) return { status: 200, data: { total: { ai_video: 4 }, affordable: false } };
      return { status: 404, data: {} };
    });
    render(<PresetUse presetId="melt-away" initialTile={MODEL} imageKey="uploads/u/cone.png" />);
    fireEvent.change(screen.getByLabelText("Your topic or link"), { target: { value: "ice cream" } });
    fireEvent.click(screen.getByRole("button", { name: /See the price/ }));
    expect((await screen.findByTestId("preset-price")).textContent).toBe("Uses 4 AI-video credits.");
    expect(screen.getByRole("link", { name: /Top up/ }).getAttribute("href")).toBe("/pricing");
    const quote = calls.find((c) => c.url.endsWith("/jobs/quote/preset"));
    expect(quote?.body).toEqual({ preset_sku: "animate_image", tier: "draft", seconds: 5 });
  });

  it("records the identity score once when a character run finishes", async () => {
    const calls = stubApi((url) => {
      if (url.endsWith("/my/brands")) return { status: 200, data: { brands: [] } };
      if (url.endsWith("/my/characters")) {
        return { status: 200, data: { characters: [{ id: "c1", name: "Me", kind: "real_face", reference_count: 12,
          trained: true, consent: { verified: true, words_heard: 6, words_total: 6 } }] } };
      }
      if (url.endsWith("/plan")) return { status: 200, data: { route: "generation/broll/generate", preset_id: "melt-away", body: { prompt: "p", mode: "i2v", image_key: "k" } } };
      if (url.endsWith("/jobs/quote/preset")) return { status: 200, data: { total: { ai_video: 4 }, affordable: true, route: { model_id: "route-a" } } };
      if (url.endsWith("/generation/broll/generate")) return { status: 200, data: { generation_id: "g1" } };
      if (url.endsWith("/presets/shelf/melt-away/runs")) return { status: 200, data: { job_id: "g1" } };
      if (url.endsWith("/presets/runs/g1")) return { status: 200, data: { job_id: "g1", preset_id: "melt-away", seconds_to_result: 90, target_seconds: 120, within_target: true } };
      if (url.endsWith("/my/characters/c1/identity-scores")) return { status: 200, data: { score: 0.93 } };
      return { status: 404, data: {} };
    });
    render(<PresetUse presetId="melt-away" initialTile={MODEL} />);
    fireEvent.change(await screen.findByLabelText("Character"), { target: { value: "c1" } });
    fireEvent.change(screen.getByLabelText("Your topic or link"), { target: { value: "ice cream" } });
    fireEvent.click(screen.getByRole("button", { name: /See the price/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Make it/ }));
    await screen.findByTestId("preset-timing");
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith("/identity-scores"))).toHaveLength(1));
    const plan = calls.find((c) => c.url.endsWith("/plan"));
    expect(plan?.body).toMatchObject({ character_id: "c1" });
    expect(calls.find((c) => c.url.endsWith("/identity-scores"))?.body).toEqual({ job_id: "g1", preset_id: "melt-away", model: "route-a" });
  });

  it("formats durations", () => {
    expect(formatSeconds(48)).toBe("48 s");
    expect(formatSeconds(134)).toBe("2 min 14 s");
  });
});
