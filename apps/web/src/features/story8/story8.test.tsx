import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/auth-state", () => ({ useSignedInState: () => ({ isLoaded: true, isSignedIn: true }) }));
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => async () => "session" }));

import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";
import { EnhancePanel } from "@/src/features/enhance";
import { Story8Panel } from "./Story8Panel";

type Route = (url: string, method: string, body: unknown) => { status: number; data: unknown };

function stubApi(route: Route) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      const { status, data } = route(url, method, body);
      const payload = { status, data, message: status === 200 ? "" : "refused" };
      return { ok: status === 200, status, statusText: "", headers: new Headers(),
        json: async () => payload, text: async () => JSON.stringify(payload) };
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const LINES = Array.from({ length: 8 }, (_, i) => `Line ${i + 1}.`);
const PLAN = {
  lines: LINES,
  frames: LINES.map((line, index) => ({ index, beat: `b${index}`, line, camera: "push_in", seconds: 3.5 })),
  quote: { seconds: 28, frames: { standard_credits: 2, ai_video_credits: 0 }, animated: { standard_credits: 2, ai_video_credits: 480 } },
};

describe("story in 8 frames", () => {
  it("writes eight editable lines, shows both prices and starts with the price shown", async () => {
    const calls = stubApi((url, method) => {
      if (url.endsWith("/film/story8/plan")) return { status: 200, data: PLAN };
      if (url.endsWith("/film/story8") && method === "POST") return { status: 200, data: { job_id: "j1", state: 4 } };
      if (url.endsWith("/film/story8/j1")) {
        return { status: 200, data: { job_id: "j1", state: 1, mode: "frames", stage: "finished", frames: PLAN.frames,
          identity_score_min: null, video_url: "https://m/final.mp4", poster_url: "https://m/p.jpg", error: "" } };
      }
      return { status: 404, data: {} };
    });
    render(<Story8Panel />);
    fireEvent.change(screen.getByLabelText("What is the story about?"), { target: { value: "a baker" } });
    fireEvent.click(screen.getByRole("button", { name: "Write the 8 frames" }));
    expect(await screen.findByText("Your 8 frames")).toBeTruthy();
    expect(screen.getByRole("button", { name: /moving frames: 2 credits$/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /480 AI-video credits/ })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Frame 3"), { target: { value: "Edited line." } });
    fireEvent.click(screen.getByRole("button", { name: /moving frames/ }));
    expect(await screen.findByText("Your story is ready")).toBeTruthy();
    const start = calls.find((c) => c.url.endsWith("/film/story8") && c.method === "POST");
    expect(start?.body).toMatchObject({ mode: "frames", quoted: { standard_credits: 2, ai_video_credits: 0 } });
    expect((start?.body as { lines: string[] }).lines[2]).toBe("Edited line.");
  });

  it("switches to a script and shows a refused start plainly", async () => {
    stubApi((url) => {
      if (url.endsWith("/film/story8/plan")) return { status: 200, data: PLAN };
      return { status: 402, data: { code: "credits_required" } };
    });
    render(<Story8Panel />);
    fireEvent.click(screen.getByRole("button", { name: "I have a script" }));
    fireEvent.change(screen.getByLabelText("Your script"), { target: { value: "One. Two." } });
    fireEvent.click(screen.getByRole("button", { name: "Write the 8 frames" }));
    fireEvent.click(await screen.findByRole("button", { name: /Animate every frame/ }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  });
});

describe("sharper and smoother", () => {
  it("quotes the video in AI-video credits and starts with that price", async () => {
    const calls = stubApi((url, method) => {
      if (url.includes("/jobs?limit=30")) return { status: 200, data: { jobs: [{ job_id: "r1", state: 1, title: "Launch" }] } };
      if (url.endsWith("/enhance/video/quote")) return { status: 200, data: { op: "upscale", ai_video_credits: 75, seconds: 5 } };
      if (url.endsWith("/enhance/video") && method === "POST") return { status: 200, data: { job_id: "e1", state: 4 } };
      if (url.endsWith("/enhance/e1")) {
        return { status: 200, data: { job_id: "e1", kind: "enhance_video", op: "upscale", state: 1,
          result_url: "https://m/up.mp4", seconds: 40, output: [1440, 2560], error: "", refunded: false } };
      }
      return { status: 404, data: {} };
    });
    render(<EnhancePanel />);
    fireEvent.change(await screen.findByLabelText("Reel"), { target: { value: "r1" } });
    fireEvent.click(screen.getByRole("button", { name: "Sharper video" }));
    expect(await screen.findByText("75 AI-video credits")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(await screen.findByText(/Download \(1440x2560\)/)).toBeTruthy();
    expect(calls.find((c) => c.url.endsWith("/enhance/video") && c.method === "POST")?.body).toEqual({
      source_job_id: "r1", op: "upscale", quoted_credits: 75 });
  });
});

describe("copy", () => {
  it("passes the copy denylist", () => {
    const web = process.cwd();
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const files = [
      "src/features/story8/Story8Panel.tsx",
      "src/features/enhance/EnhancePanel.tsx",
      "app/story/page.tsx",
      "app/enhance/page.tsx",
    ];
    const units = files.flatMap((rel) => sourceUnits(fs.readFileSync(path.join(web, rel), "utf8"), rel).units);
    expect(checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error")).toEqual([]);
  });
});
