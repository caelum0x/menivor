/**
 * Wiring tests for the Clipfarm API layer (`lib/series.ts`). Asserts each client
 * hits the correct endpoint/method/body and forwards the `Idempotency-Key` on
 * the trigger paths. `fetch` is mocked IN-TEST only — the product code always
 * talks to the real backend router (`app/domains/series/router.py`).
 */

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import {
  getChannelPacing,
  getChannelRun,
  listChannelRuns,
  triggerChannelRun,
  triggerChannelSchedule,
  type ChannelPacing,
  type ChannelRunView,
} from "@/lib/series";
import { ApiError } from "@/src/shared/api";

type FetchArgs = Parameters<typeof fetch>;

const runRow: ChannelRunView = {
  id: "run-1",
  channel_id: "chan-9",
  user_id: "user-1",
  params: {
    run_id: "rr-abc",
    summary: {
      planned: 3,
      skipped_duplicates: 1,
      paced_out: 0,
      rendered: 2,
      enqueue_failures: 0,
    },
  },
  created_at: "2026-08-19T00:00:00+00:00",
};

const pacing: ChannelPacing = {
  pending: [
    {
      id: "clip-1",
      channel_id: "chan-9",
      run_id: "rr-abc",
      spec_hash: "abc123",
      job_id: "job-1",
      account: "acct-a",
      platform: "tiktok",
      status: "pending",
      scheduled_publish_id: null,
      created_at: "2026-08-19T00:00:00+00:00",
    },
  ],
  rendered_today: { "acct-a": 2 },
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

describe("listChannelRuns", () => {
  it("GETs the channel's runs with a clamped limit", async () => {
    mockFetchOnce({ runs: [runRow] });

    const res = await listChannelRuns("chan-9", 50, { token: "k1" });

    expect(res.runs).toEqual([runRow]);
    const { url, init } = lastCall();
    expect(url).toContain("/series/channels/chan-9/runs?limit=50");
    expect(init.method ?? "GET").toBe("GET");
    expect((init.headers as Record<string, string>)["x-api-key"]).toBe("k1");
    expect(init.body).toBeUndefined();
  });

  it("clamps the limit into the backend-accepted 1..200 range", async () => {
    mockFetchOnce({ runs: [] });
    await listChannelRuns("chan-9", 9999);
    expect(lastCall().url).toContain("limit=200");

    mockFetchOnce({ runs: [] });
    await listChannelRuns("chan-9", 0);
    expect(lastCall().url).toContain("limit=50");
  });

  it("URL-encodes the channel id path segment", async () => {
    mockFetchOnce({ runs: [] });
    await listChannelRuns("a b/c");
    expect(lastCall().url).toContain("/series/channels/a%20b%2Fc/runs");
  });

  it("throws ApiError on a non-2xx response", async () => {
    mockFetchOnce({ message: "boom" }, false, 503);
    await expect(listChannelRuns("chan-9")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("getChannelRun", () => {
  it("GETs a single run by id", async () => {
    mockFetchOnce(runRow);
    const res = await getChannelRun("run-1", { token: "k2" });
    expect(res).toEqual(runRow);
    const { url, init } = lastCall();
    expect(url).toContain("/series/runs/run-1");
    expect(init.method ?? "GET").toBe("GET");
  });
});

describe("getChannelPacing", () => {
  it("GETs the pending/pacing snapshot", async () => {
    mockFetchOnce(pacing);
    const res = await getChannelPacing("chan-9");
    expect(res.pending).toHaveLength(1);
    expect(res.rendered_today).toEqual({ "acct-a": 2 });
    const { url, init } = lastCall();
    expect(url).toContain("/series/channels/chan-9/pending");
    expect(init.method ?? "GET").toBe("GET");
  });
});

describe("triggerChannelRun", () => {
  it("POSTs the run body and forwards the Idempotency-Key", async () => {
    mockFetchOnce({
      run_id: "rr-xyz",
      summary: {
        planned: 1,
        skipped_duplicates: 0,
        paced_out: 0,
        rendered: 1,
        enqueue_failures: 0,
      },
    });

    const res = await triggerChannelRun(
      "chan-9",
      {
        source_items: [{ body: "a reddit story" }],
        platforms: ["tiktok"],
        subject: "stories",
      },
      { token: "k3", idempotencyKey: "idem-run-1" },
    );

    expect(res.run_id).toBe("rr-xyz");
    const { url, init } = lastCall();
    expect(url).toContain("/series/channels/chan-9/run");
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toBe("idem-run-1");
    expect(headers["Content-Type"]).toBe("application/json");
    const body = JSON.parse(String(init.body));
    expect(body.source_items).toHaveLength(1);
    expect(body.source_items[0].body).toBe("a reddit story");
    expect(body.platforms).toEqual(["tiktok"]);
    expect(body.subject).toBe("stories");
    // Unset overrides serialize to null / empty (never omitted → forbid-safe).
    expect(body.max_words).toBe(null);
    expect(body.hooks).toEqual([]);
  });
});

describe("triggerChannelSchedule", () => {
  it("POSTs the schedule body and forwards the Idempotency-Key", async () => {
    mockFetchOnce({ summary: { considered: 1, scheduled: 1 } });

    const res = await triggerChannelSchedule(
      "chan-9",
      { platforms: ["tiktok", "instagram"] },
      { token: "k4", idempotencyKey: "idem-sched-1" },
    );

    expect(res.summary.scheduled).toBe(1);
    const { url, init } = lastCall();
    expect(url).toContain("/series/channels/chan-9/schedule");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBe(
      "idem-sched-1",
    );
    const body = JSON.parse(String(init.body));
    expect(body.platforms).toEqual(["tiktok", "instagram"]);
    expect(body.accounts).toEqual([]);
  });

  it("defaults to empty platforms/accounts when no input is given", async () => {
    mockFetchOnce({ summary: { considered: 0, scheduled: 0 } });
    await triggerChannelSchedule("chan-9");
    const body = JSON.parse(String(lastCall().init.body));
    expect(body.platforms).toEqual([]);
    expect(body.accounts).toEqual([]);
  });
});
