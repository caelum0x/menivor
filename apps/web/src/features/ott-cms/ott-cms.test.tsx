import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const token = async () => "session";
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => token }));

import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";
import { OttStudio } from "./OttStudio";

function stubApi(route: (url: string, method: string) => { status: number; data: unknown }) {
  const calls: { url: string; method: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method });
    const { status, data } = route(url, method);
    const payload = { status, data, message: "" };
    return { ok: status === 200, status, statusText: "", headers: new Headers(), json: async () => payload, text: async () => JSON.stringify(payload) };
  }));
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const TITLE = { id: "t1", title: "Reel 1", synopsis: "", kind: "short", artwork_url: "", duration_s: 30, genres: [], rating: "",
  access_tier: "free", status: "published", hidden_reason: "", package_status: "none", source_job_id: "j1" };
const CHANNEL = { id: "c1", handle: "maya", title: "Maya", tagline: "", layout: "grid", brand_colors: [], status: "draft",
  storefront_path: "/c/maya", titles: [], series: [], collections: [] };

describe("OTT studio", () => {
  it("publishes the channel in one press and shows the measured time", async () => {
    const calls = stubApi((url, method) => {
      if (url.endsWith("/ott/studio") && method === "GET") return { status: 200, data: CHANNEL };
      if (url.endsWith("/ott/studio/publish-all")) {
        return { status: 200, data: { channel: { ...CHANNEL, status: "published", titles: [TITLE] }, published: ["t1"], held: [],
          seconds: 1.4, target_seconds: 60, within_target: true } };
      }
      if (url.endsWith("/ott/studio/titles/t1/unpublish")) return { status: 200, data: { ...TITLE, status: "hidden" } };
      return { status: 404, data: {} };
    });
    render(<OttStudio />);
    fireEvent.click(await screen.findByRole("button", { name: /Publish my finished reels/ }));
    expect(await screen.findByText("1 titles live in 1.4 s.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open my channel" }).getAttribute("href")).toBe("/c/maya");
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    await new Promise((r) => setTimeout(r, 0));
    expect(calls.some((c) => c.url.endsWith("/ott/studio/titles/t1/unpublish") && c.method === "POST")).toBe(true);
  });

  it("passes the copy denylist", () => {
    const web = process.cwd();
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const files = ["src/features/ott-cms/OttStudio.tsx", "app/studio-ott/page.tsx"];
    const units = files.flatMap((rel) => sourceUnits(fs.readFileSync(path.join(web, rel), "utf8"), rel).units);
    expect(checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error")).toEqual([]);
  });
});

describe("resumable upload", () => {
  it("uploads only the missing parts after an interruption and keeps part order", async () => {
    const { uploadFile } = await import("./uploader");
    const memory = new Map<string, string>();
    const store = { getItem: (k: string) => memory.get(k) ?? null, setItem: (k: string, v: string) => void memory.set(k, v),
      removeItem: (k: string) => void memory.delete(k) };
    stubApi((url) => {
      if (url.endsWith("/ott/uploads")) return { status: 200, data: { key: "ott-uploads/u/1/f.mp4", upload_id: "up", part_size: 4, parts: 3 } };
      if (url.endsWith("/ott/uploads/parts")) return { status: 200, data: { urls: { 1: "u1", 2: "u2", 3: "u3" } } };
      return { status: 404, data: {} };
    });
    const file = new File(["abcdefghij"], "f.mp4", { type: "video/mp4", lastModified: 1 });
    let fail = true;
    const put = async (url: string, blob: Blob) => {
      if (url === "u2" && fail) throw new Error("network dropped");
      return `etag-${url}-${blob.size}`;
    };
    await expect(uploadFile(file, { store, putPart: put })).rejects.toThrow("network dropped");
    fail = false;
    const seen: string[] = [];
    const done = await uploadFile(file, { store, putPart: async (url, blob) => { seen.push(url); return put(url, blob); } });
    expect(seen).toEqual(["u2", "u3"]);
    expect(done.done.map((p) => p.PartNumber)).toEqual([1, 2, 3]);
    expect(done.done[2]?.ETag).toBe("etag-u3-2");
  });
});
