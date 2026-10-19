/**
 * Unit tests for the Trends Feed API layer (the additions this feature owns in
 * `lib/trends.ts`: getRecommendedTrends + observeTrends), plus the existing
 * rankTrends/parseTrendLines they build on. `fetch` is mocked IN-TEST only — the
 * product code always talks to the real API.
 */

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import {
  getRecommendedTrends,
  observeTrends,
  parseTrendLines,
  rankTrends,
  type ObservedTrend,
} from "@/lib/trends";
import { ApiError } from "@/src/shared/api";

type FetchArgs = Parameters<typeof fetch>;

const observedRow: ObservedTrend = {
  id: "7",
  trend_id: "dance_sound",
  kind: "sound",
  label: "Dance sound",
  opportunity: 0.82,
  saturation: 0.31,
  phase: "rising",
  recommend: true,
};

function mockFetchOnce(data: unknown, ok = true, status = 200): void {
  (global.fetch as Mock).mockResolvedValueOnce({
    ok,
    status,
    text: async () => JSON.stringify({ status, data }),
    headers: { get: () => null },
  });
}

function lastCall(): { url: string; init: RequestInit } {
  const calls = (global.fetch as Mock).mock.calls as FetchArgs[];
  const [url, init] = calls[calls.length - 1]!;
  return { url: String(url), init: (init ?? {}) as RequestInit };
}

beforeEach(() => {
  global.fetch = vi.fn() as unknown as typeof fetch;
});

afterEach(() => {
  vi.resetAllMocks();
});

describe("getRecommendedTrends", () => {
  it("GETs the recommended feed and unwraps the envelope data", async () => {
    mockFetchOnce({ trends: [observedRow] });

    const res = await getRecommendedTrends(30, { token: "k1" });

    expect(res.trends).toEqual([observedRow]);
    const { url, init } = lastCall();
    expect(url).toContain("/trends/recommended?limit=30");
    // Default method is GET (no explicit method set).
    expect(init.method ?? "GET").toBe("GET");
    expect((init.headers as Record<string, string>)["x-api-key"]).toBe("k1");
    expect(init.body).toBeUndefined();
  });

  it("clamps the limit into the backend-accepted 1..100 range", async () => {
    mockFetchOnce({ trends: [] });
    await getRecommendedTrends(9999);
    expect(lastCall().url).toContain("limit=100");

    mockFetchOnce({ trends: [] });
    await getRecommendedTrends(0);
    // 0 || 20 → default 20
    expect(lastCall().url).toContain("limit=20");
  });

  it("throws ApiError on a non-2xx response", async () => {
    mockFetchOnce({ message: "boom" }, false, 503);
    await expect(getRecommendedTrends(10)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("observeTrends", () => {
  it("POSTs the candidate series and returns the persisted rows", async () => {
    mockFetchOnce({ observed: [observedRow] });

    const res = await observeTrends(
      [{ trend_id: "dance_sound", kind: "sound", counts: [1, 2, 3] }],
      { token: "k2" },
    );

    expect(res.observed).toEqual([observedRow]);
    const { url, init } = lastCall();
    expect(url).toContain("/trends/observe");
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body.trends).toHaveLength(1);
    expect(body.trends[0].trend_id).toBe("dance_sound");
    expect(body.limit).toBe(20);
  });
});

describe("rankTrends", () => {
  it("POSTs to /trends/rank with the candidate series", async () => {
    mockFetchOnce({ trends: [] });
    await rankTrends([{ trend_id: "x", counts: [1, 2] }]);
    const { url, init } = lastCall();
    expect(url).toContain("/trends/rank");
    expect(init.method).toBe("POST");
  });
});

describe("parseTrendLines", () => {
  it("parses well-formed lines and skips blanks/malformed", () => {
    const out = parseTrendLines(
      "dance: 100, 400, 1200\n\n: 1,2,3\nnope\nmeme: 5,6",
    );
    expect(out).toEqual([
      { trend_id: "dance", kind: "custom", counts: [100, 400, 1200] },
      { trend_id: "meme", kind: "custom", counts: [5, 6] },
    ]);
  });
});
