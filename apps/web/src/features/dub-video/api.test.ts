import { afterEach, describe, expect, it, vi } from "vitest";

import { createDub, getDub, isTerminalDub, languageLabel, listDubs } from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: status < 400 ? "OK" : "Error",
    text: async () => JSON.stringify(body),
    headers: { get: () => null },
  } as unknown as Response;
}

function mockFetch() {
  const fn = vi.fn();
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("dub api", () => {
  it("POSTs /dub/videos with the chosen options", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ status: 200, data: { dub_id: "d1", state: "processing", progress: 0 } }),
    );
    const job = await createDub(
      { video_key: "uploads/a.mp4", source_language: "en", target_language: "tr", voice_engine: "edge" },
      { token: "tok" },
    );
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/dub/videos");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toMatchObject({ video_key: "uploads/a.mp4", target_language: "tr" });
    expect(job.dub_id).toBe("d1");
  });

  it("lists dubs with a clamped limit and tolerates a missing array", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 200, data: {} }));
    const rows = await listDubs(500, { token: "tok" });
    expect(fetchMock.mock.calls[0]![0]).toContain("/dub/videos?limit=50");
    expect(rows).toEqual([]);
  });

  it("encodes the id when polling", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 200, data: { dub_id: "a/b", state: "complete" } }));
    await getDub("a/b", { token: "tok" });
    expect(fetchMock.mock.calls[0]![0]).toContain("/dub/videos/a%2Fb");
  });

  it("knows terminal states and language labels", () => {
    expect(isTerminalDub({ state: "processing" })).toBe(false);
    expect(isTerminalDub({ state: "failed" })).toBe(true);
    expect(languageLabel([{ code: "tr", label: "Turkish", voices: [] }], "tr")).toBe("Turkish");
    expect(languageLabel([], "xx")).toBe("xx");
  });
});
