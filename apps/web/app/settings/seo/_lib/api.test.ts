import { afterEach, describe, expect, it, vi } from "vitest";

import {
  addRankKeywords,
  connectSeo,
  getSeoOverview,
  removeRankKeyword,
  researchKeywords,
  scopeQuery,
  validateOpenSeoKey,
} from "./api";

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    text: async () => JSON.stringify({ status: 200, data: body }),
    headers: { get: () => null },
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("scopeQuery and validateOpenSeoKey", () => {
  it("builds the workspace query", () => {
    expect(scopeQuery()).toBe("");
    expect(scopeQuery({ workspaceId: "ws1" })).toBe("?workspace_id=ws1");
    expect(scopeQuery({ workspaceId: null })).toBe("");
  });

  it("rejects short, long or spaced keys", () => {
    expect(validateOpenSeoKey("short")).toMatch(/full/);
    expect(validateOpenSeoKey("a".repeat(301))).toMatch(/too long/);
    expect(validateOpenSeoKey("has a space here")).toMatch(/spaces/);
    expect(validateOpenSeoKey("oseo_live_key_12345")).toBeNull();
  });
});

describe("requests", () => {
  it("connects with a trimmed key and domain, scoped by workspace", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ connected: true, project_id: "proj_1" }));
    vi.stubGlobal("fetch", fetchMock);
    const out = await connectSeo("  oseo_live_key_12345  ", " example.com ", { workspaceId: "ws1" }, { token: "t" });
    expect(out.connected).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toContain("/seo/connect?workspace_id=ws1");
    expect(JSON.parse(init.body)).toEqual({ api_key: "oseo_live_key_12345", domain: "example.com" });
  });

  it("reads the overview without a body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ connected: false, can_manage: true }));
    vi.stubGlobal("fetch", fetchMock);
    const out = await getSeoOverview({}, { token: "t" });
    expect(out).toEqual({ connected: false, can_manage: true });
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toContain("/seo/overview");
    expect(init.body).toBeUndefined();
  });

  it("filters blank seeds and keywords before sending", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ keywords: [] }))
      .mockResolvedValueOnce(jsonResponse({ keywords: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await researchKeywords(["  tracker  ", "", "   "], {});
    const [, firstInit] = fetchMock.mock.calls[0] ?? [];
    expect(JSON.parse(firstInit.body)).toEqual({ seeds: ["tracker"] });
    await addRankKeywords(["  alpha  ", ""], "us", {});
    const [, secondInit] = fetchMock.mock.calls[1] ?? [];
    expect(JSON.parse(secondInit.body)).toEqual({ keywords: ["alpha"], country: "us" });
  });

  it("removes a tracked keyword by id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ removed: true }));
    vi.stubGlobal("fetch", fetchMock);
    const out = await removeRankKeyword("kw-1", { workspaceId: "ws1" });
    expect(out.removed).toBe(true);
    const [url] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toContain("/seo/rank-tracker/keywords/kw-1?workspace_id=ws1");
  });
});
