import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
const apiRequest = vi.fn();
vi.mock("@/src/shared/api", () => ({ apiRequest: (...args: unknown[]) => apiRequest(...args) }));

import { NewThisWeek } from "./NewThisWeek";
import type { PresetTile } from "@/src/features/presets-shelf/api";
import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";

const TILE: PresetTile = {
  id: "petal-burst",
  name: "Petal burst",
  blurb: "Your subject bursts into petals.",
  kind: "model",
  credit_kind: "ai_video",
  credit_label: "AI-video credits",
  inputs: ["subject", "image"],
  preview: { loop_url: "https://media.example/presets/petal-burst.mp4", poster_url: "https://media.example/presets/petal-burst.jpg" },
  create_url: "/presets-gallery?use=petal-burst",
  target_seconds: 120,
};

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
});

describe("NewThisWeek", () => {
  it("renders nothing before a drop is released", () => {
    const { container } = render(<NewThisWeek initialDrop={{ week: null, presets: [] }} />);
    expect(container.innerHTML).toBe("");
  });

  it("shows the drop tiles with moving previews and one tap into Create", () => {
    render(<NewThisWeek initialDrop={{ week: "2026-W41", presets: [TILE] }} />);
    expect(screen.getByRole("heading", { name: "New this week" })).toBeTruthy();
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("/presets-gallery?use=petal-burst");
    expect(screen.getByLabelText("Petal burst preview").getAttribute("src")).toContain("petal-burst.mp4");
  });

  it("fetches the latest drop from the public route without a sign-in", async () => {
    apiRequest.mockResolvedValueOnce({ week: "2026-W41", presets: [TILE] });
    render(<NewThisWeek />);
    await waitFor(() => expect(screen.getByText("Petal burst")).toBeTruthy());
    expect(apiRequest.mock.calls[0]?.[0]).toBe("/presets/drops/latest");
    expect(apiRequest.mock.calls[0]?.[1]).toMatchObject({ anonymous: true });
  });
});

describe("copy", () => {
  it("passes the copy denylist", () => {
    const web = path.resolve(__dirname, "../../..");
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const files = ["src/features/preset-drops/NewThisWeek.tsx"];
    const units = files.flatMap((rel) => sourceUnits(fs.readFileSync(path.join(web, rel), "utf8"), rel).units);
    expect(checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error")).toEqual([]);
  });
});
