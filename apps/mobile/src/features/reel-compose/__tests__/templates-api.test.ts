/**
 * Unit tests for the Reel Compose API additions this feature owns in
 * `lib/templates.ts`: getTemplate + getPopularTemplates + getTemplateHistory.
 * `fetch` is mocked IN-TEST only — product code always hits the real API.
 */

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import {
  getPopularTemplates,
  getTemplate,
  getTemplateHistory,
  type PopularTemplate,
  type TemplateDetail,
  type TemplateHistoryEntry,
} from "@/lib/templates";

type FetchArgs = Parameters<typeof fetch>;

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

describe("getTemplate", () => {
  it("GETs /templates/{slug} with the session token and unwraps the detail", async () => {
    const detail: Partial<TemplateDetail> = {
      slug: "asmr_loop",
      name: "ASMR Loop",
      inputs: [],
      slots: [],
    };
    mockFetchOnce(detail);

    const res = await getTemplate("asmr_loop", { token: "k1" });

    expect(res.slug).toBe("asmr_loop");
    const { url, init } = lastCall();
    expect(url).toContain("/templates/asmr_loop");
    expect(init.method ?? "GET").toBe("GET");
    expect((init.headers as Record<string, string>)["x-api-key"]).toBe("k1");
  });

  it("URL-encodes a slug containing unsafe characters", async () => {
    mockFetchOnce({ slug: "a/b" });
    await getTemplate("a/b");
    expect(lastCall().url).toContain("/templates/a%2Fb");
  });
});

describe("getPopularTemplates", () => {
  it("GETs the analytics feed and returns the popular rows", async () => {
    const rows: PopularTemplate[] = [
      { template_slug: "asmr_loop", count: 42 },
      { template_slug: "movie_recap", count: 17 },
    ];
    mockFetchOnce({ popular: rows });

    const res = await getPopularTemplates({ token: "k1" }, 5);

    expect(res).toEqual(rows);
    const { url } = lastCall();
    expect(url).toContain("/templates/analytics/popular?limit=5");
  });

  it("degrades to [] when the payload omits the popular array", async () => {
    mockFetchOnce({});
    const res = await getPopularTemplates();
    expect(res).toEqual([]);
  });
});

describe("getTemplateHistory", () => {
  it("GETs the caller's history and returns the rows", async () => {
    const rows: TemplateHistoryEntry[] = [
      {
        id: "i1",
        template_slug: "asmr_loop",
        template_version: "1.0",
        duration_s: 30,
        reel_job_id: "job_1",
      },
    ];
    mockFetchOnce({ history: rows });

    const res = await getTemplateHistory({ token: "k1" }, 25);

    expect(res).toEqual(rows);
    expect(lastCall().url).toContain("/templates/history?limit=25");
  });

  it("degrades to [] when history is missing", async () => {
    mockFetchOnce({ nope: true });
    expect(await getTemplateHistory()).toEqual([]);
  });
});
