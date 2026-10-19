import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const signed = { isLoaded: true, isSignedIn: true };
vi.mock("@/lib/auth-state", () => ({ useSignedInState: () => signed }));
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => async () => "session" }));

import { ShowcaseWall } from "@/components/marketing/showcase/ShowcaseWall";
import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";
import type { GalleryItem } from "./api";
import { GalleryFeed } from "./GalleryFeed";
import { PublishPicker } from "./PublishPicker";
import { RecreatePanel } from "./RecreatePanel";
import { galleryWallMedia, toShowcaseMedia } from "./wall";

const ITEM: GalleryItem = {
  id: "item1",
  title: "Espresso bar opening",
  preset_id: "shelf:crash-zoom",
  preset_name: "Crash zoom",
  remix_count: 3,
  preview_url: "https://signed.example/preview.mp4",
  poster_url: "https://signed.example/poster.jpg",
  published_at: "2026-09-30T10:00:00+00:00",
  recreate_url: "/gallery?recreate=item1",
  provenance: { ai_generated: true, content_id: "job1", report_url: "https://menivor.com/legal/report", generator: "Menivor" },
};

type Route = (url: string, method: string) => { status: number; data: unknown };

function stubApi(route: Route) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      const { status, data } = route(url, method);
      const payload = { status, data, message: status === 200 ? "" : "refused" };
      return { ok: status === 200, status, statusText: "", headers: new Headers(),
        json: async () => payload, text: async () => JSON.stringify(payload) };
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
});

describe("gallery feed", () => {
  it("shows moving items with provenance and a Recreate link", () => {
    render(<GalleryFeed initialItems={[ITEM]} />);
    expect((screen.getByLabelText("Espresso bar opening preview") as HTMLVideoElement).muted).toBe(true);
    expect(screen.getByTestId("provenance").textContent).toContain("AI-generated with Menivor");
    const recreate = screen.getByRole("link", { name: /Recreate \(3\)/ });
    expect(recreate.getAttribute("href")).toBe("/gallery?recreate=item1");
  });

  it("empty gallery invites an opt-in, never shows placeholders", async () => {
    stubApi(() => ({ status: 200, data: { items: [] } }));
    render(<GalleryFeed />);
    expect(await screen.findByRole("link", { name: /Show one of your reels/ })).toBeTruthy();
    expect(document.querySelectorAll("video")).toHaveLength(0);
  });

  it("passes the copy denylist", () => {
    const web = path.resolve(__dirname, "../../..");
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const files = ["GalleryFeed.tsx", "RecreatePanel.tsx", "PublishPicker.tsx"].map((rel) => [
      path.join(__dirname, rel), `src/features/gallery/${rel}`,
    ]);
    files.push([path.resolve(web, "app/(marketing)/gallery/page.tsx"), "app/(marketing)/gallery/page.tsx"]);
    const units = files.flatMap(([abs, rel]) => sourceUnits(fs.readFileSync(abs as string, "utf8"), rel as string).units);
    expect(checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error")).toEqual([]);
  });
});

describe("recreate", () => {
  it("prices first, then makes it and links the remix to the item", async () => {
    const calls = stubApi((url) => {
      if (url.endsWith("/gallery/item1/recreate")) {
        return { status: 200, data: { route: "jobs", item_id: "item1", body: { params: { camera_motion: "crash_zoom_in" }, variants: 1 } } };
      }
      if (url.endsWith("/jobs/quote")) return { status: 200, data: { total: { standard: 1 }, affordable: true } };
      if (url.endsWith("/jobs")) return { status: 200, data: { job_id: "job9" } };
      if (url.endsWith("/gallery/item1/remixes")) return { status: 200, data: { item_id: "item1", job_id: "job9" } };
      return { status: 404, data: {} };
    });
    render(<RecreatePanel itemId="item1" initialItem={ITEM} />);
    fireEvent.change(screen.getByLabelText("Your topic or link"), { target: { value: "My bakery" } });
    fireEvent.click(screen.getByRole("button", { name: /See the price/ }));
    expect((await screen.findByTestId("recreate-price")).textContent).toBe("Uses 1 credit.");
    fireEvent.click(screen.getByRole("button", { name: /Make it/ }));
    await waitFor(() => expect(screen.getByRole("link", { name: "Open the result" }).getAttribute("href")).toBe("/jobs/job9"));
    const recreate = calls.find((c) => c.url.endsWith("/gallery/item1/recreate"));
    expect(recreate?.body).toEqual({ subject: "My bakery" });
    const link = calls.find((c) => c.url.endsWith("/gallery/item1/remixes"));
    expect(link?.body).toEqual({ job_id: "job9" });
  });

  it("sends a signed-out visitor to sign up and back", () => {
    signed.isSignedIn = false;
    render(<RecreatePanel itemId="item1" initialItem={ITEM} />);
    const link = screen.getByRole("link", { name: /Sign up with your email/ });
    expect(decodeURIComponent(link.getAttribute("href") ?? "")).toContain("/gallery?recreate=item1");
  });
});

describe("publish picker", () => {
  it("lists only finished reels and publishes the one you pick", async () => {
    const calls = stubApi((url, method) => {
      if (url.includes("/jobs?limit=30")) {
        return { status: 200, data: { jobs: [{ job_id: "a", state: 1, title: "Done" }, { job_id: "b", state: 4 }] } };
      }
      if (url.endsWith("/gallery") && method === "POST") return { status: 200, data: { id: "item7", job_id: "a" } };
      return { status: 404, data: {} };
    });
    render(<PublishPicker />);
    fireEvent.click(await screen.findByRole("button", { name: "Show" }));
    expect(await screen.findByText("Shown")).toBeTruthy();
    expect(screen.getAllByLabelText("Title")).toHaveLength(1);
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({ job_id: "a", title: "Done" });
  });
});

describe("landing wall data source", () => {
  it("adds at most six gallery items after the showcase reels", async () => {
    stubApi(() => ({ status: 200, data: { items: Array.from({ length: 8 }, (_, n) => ({ ...ITEM, id: `i${n}` })) } }));
    const gallery = await galleryWallMedia("shops");
    expect(gallery).toHaveLength(6);
    render(<ShowcaseWall id="shops" title="Shops" subline="Line" reels={[]} gallery={gallery} />);
    expect(document.querySelectorAll("li")).toHaveLength(6);
  });

  it("maps an item to a moving tile and survives an outage", async () => {
    const media = toShowcaseMedia(ITEM, "life");
    expect(media.mp4).toBe(ITEM.preview_url);
    expect(media.key).toBe("gallery-item1");
    stubApi(() => ({ status: 500, data: {} }));
    expect(await galleryWallMedia("life")).toEqual([]);
  });

  it("gives up on a slow API so the landing never waits on the gallery (P-M2)", async () => {
    vi.stubGlobal("fetch", (_url: string, init?: RequestInit) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("timeout", "AbortError")));
      }));
    expect(await galleryWallMedia("shops", 20)).toEqual([]);
  });

  it("the landing page feeds the gallery into the first wall only (P-M2)", () => {
    const source = fs.readFileSync(path.join(process.cwd(), "app", "(marketing)", "page.tsx"), "utf8");
    expect(source).toContain("await galleryWallMedia(firstGroup)");
    expect(source).toContain("gallery={index === 0 ? gallery : []}");
  });
});
