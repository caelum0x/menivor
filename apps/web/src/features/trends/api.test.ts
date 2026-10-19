import { afterEach, describe, expect, it, vi } from "vitest";

import { getTrendsFeed, parseTrendLines, rankTrends } from "./api";

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
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

describe("getTrendsFeed", () => {
  it("calls GET /trends/recommended with a limit and returns ranked rows", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          trends: [
            {
              id: "t1",
              trend_id: "dance-loop",
              kind: "sound",
              label: "Dance loop",
              opportunity: 0.82,
              saturation: 0.2,
              phase: "rising",
              recommend: true,
            },
          ],
        },
      }),
    );

    const res = await getTrendsFeed({ limit: 20 }, { token: "tok" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/trends/recommended?limit=20");
    expect(init.method).toBe("GET");
    expect(res.trends).toHaveLength(1);
    expect(res.trends[0]!.recommend).toBe(true);
    expect(res.trends[0]!.opportunity).toBeCloseTo(0.82);
  });
});

describe("rankTrends", () => {
  it("POSTs /trends/rank with the parsed trend inputs", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ status: 200, data: { trends: [] } }),
    );

    await rankTrends({ trends: parseTrendLines("x: 1,2,3"), limit: 50 }, { token: "tok" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/trends/rank");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body).trends[0].trend_id).toBe("x");
  });
});

describe("parseTrendLines", () => {
  it("parses id + counts lines and drops empties", () => {
    const parsed = parseTrendLines("a: 1,2,3\n\nb: 10, 20 ,30\njunk: x,y");
    expect(parsed).toHaveLength(2);
    expect(parsed[0]).toEqual({ trend_id: "a", kind: "custom", counts: [1, 2, 3] });
    expect(parsed[1]!.counts).toEqual([10, 20, 30]);
  });
});
