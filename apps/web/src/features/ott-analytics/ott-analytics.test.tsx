import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";

const token = vi.hoisted(() => async () => "session");
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => token }));
const apiRequest = vi.fn();
vi.mock("@/src/shared/api", () => ({ API_BASE: "https://api.example/api/v1", apiRequest: (...a: unknown[]) => apiRequest(...a) }));

import { trackQuality, type BeaconEvent } from "./beacons";
import { AnalyticsPanel } from "./AnalyticsPanel";

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
  vi.useRealTimers();
});

describe("quality beacons", () => {
  it("measure startup, watch time and stalls, and send only to our API", () => {
    vi.useFakeTimers();
    let clock = 0;
    const batches: (readonly BeaconEvent[])[] = [];
    const video = document.createElement("video");
    let t = 0;
    Object.defineProperty(video, "currentTime", { get: () => t, configurable: true });
    const stop = trackQuality(video, "t1", { send: (events) => batches.push(events), now: () => clock });
    clock = 850;
    video.dispatchEvent(new Event("playing"));
    for (const at of [1, 2, 3, 4]) {
      t = at;
      video.dispatchEvent(new Event("timeupdate"));
    }
    clock = 5000;
    video.dispatchEvent(new Event("waiting"));
    clock = 6200;
    video.dispatchEvent(new Event("playing"));
    t = 30;
    video.dispatchEvent(new Event("timeupdate"));
    vi.advanceTimersByTime(15_000);
    stop();
    const events = batches.flat();
    expect(events.find((e) => e.event === "start")?.startup_ms).toBe(850);
    expect(events.find((e) => e.event === "stall")?.stall_ms).toBe(1200);
    expect(events.find((e) => e.event === "heartbeat")?.watched_s).toBe(4);
    expect(new Set(events.map((e) => e.session_id)).size).toBe(1);
  });

  it("post to the first-party route only", () => {
    const source = fs.readFileSync(path.join(__dirname, "beacons.ts"), "utf8");
    expect(source).toContain('"/ott/beacons"');
    expect(source).not.toMatch(/google|segment|mixpanel|amplitude|posthog|facebook/i);
  });
});

describe("AnalyticsPanel", () => {
  it("shows totals, per-title quality and the team", async () => {
    apiRequest.mockImplementation(async (route: string) => route.startsWith("/ott/studio/analytics")
      ? { channel: "maya", days: 7, totals: { plays: 6, viewers: 3, watch_minutes: 4, stalls: 3, errors: 1, beacons: 30 },
          titles: [{ title_id: "t1", title: "Bread", plays: 4, watch_minutes: 3, stalls: 2, errors: 0, startup_p95_ms: 1100 }], daily: [] }
      : { members: [{ id: "m1", email: "a@example.com", role: "analyst" }] });
    render(<AnalyticsPanel />);
    await waitFor(() => screen.getByText(/6 plays, 3 viewers, 4 minutes watched/));
    expect(screen.getByText("1.1 s")).toBeTruthy();
    expect(screen.getByText(/a@example.com \(analyst\)/)).toBeTruthy();
  });

  it("passes the copy denylist", () => {
    const web = path.resolve(__dirname, "../../..");
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const files = ["src/features/ott-analytics/AnalyticsPanel.tsx", "src/features/ott-ai/AiPanel.tsx",
      "src/features/ott-ai/Chapters.tsx", "src/features/ott-discovery/SearchBox.tsx", "src/features/ott-discovery/AskVideo.tsx"];
    const units = files.flatMap((rel) => sourceUnits(fs.readFileSync(path.join(web, rel), "utf8"), rel).units);
    expect(checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error")).toEqual([]);
  });
});
