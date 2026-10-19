/**
 * Unit tests for the ClipMarket API additions this feature owns in
 * `lib/clipmarket.ts`: setCampaignStatus + submitClip + reviewSubmission. These
 * assert endpoint / method / body / header wiring against the real shared
 * client. `fetch` is mocked IN-TEST only — product code always hits the real API.
 */

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import {
  reviewSubmission,
  setCampaignStatus,
  submitClip,
  type Campaign,
  type Submission,
} from "@/lib/clipmarket";
import { ApiError } from "@/src/shared/api";

type FetchArgs = Parameters<typeof fetch>;

const campaign: Campaign = {
  id: "camp_1",
  brand_id: "brand_1",
  title: "Summer push",
  cpm_micros: 3_000_000,
  budget_micros: 100_000_000,
  spent_micros: 12_000_000,
  min_views: 500,
  status: "paused",
};

const submission: Submission = {
  id: "sub_1",
  campaign_id: "camp_1",
  clipper_id: "clip_1",
  clip_url: "https://youtu.be/abc",
  verified_views: 1200,
  payable_micros: 3_600_000,
  status: "approved",
  fraud_score: 0.1,
  fraud_flags: [],
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

function headers(init: RequestInit): Record<string, string> {
  return (init.headers ?? {}) as Record<string, string>;
}

beforeEach(() => {
  global.fetch = vi.fn() as unknown as typeof fetch;
});

afterEach(() => {
  vi.resetAllMocks();
});

describe("setCampaignStatus", () => {
  it("POSTs the status to /clipmarket/campaigns/{id}/status", async () => {
    mockFetchOnce(campaign);

    const res = await setCampaignStatus("camp_1", { status: "paused" }, { token: "k1" });

    expect(res).toEqual(campaign);
    const { url, init } = lastCall();
    expect(url).toContain("/clipmarket/campaigns/camp_1/status");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ status: "paused" });
    expect(headers(init)["x-api-key"]).toBe("k1");
  });

  it("URL-encodes a campaign id with unsafe characters", async () => {
    mockFetchOnce(campaign);
    await setCampaignStatus("a/b", { status: "ended" });
    expect(lastCall().url).toContain("/clipmarket/campaigns/a%2Fb/status");
  });

  it("throws ApiError on a non-2xx response", async () => {
    mockFetchOnce({ message: "not owner" }, false, 422);
    await expect(
      setCampaignStatus("camp_1", { status: "active" }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe("submitClip", () => {
  it("POSTs the clip_url and sends the Idempotency-Key header", async () => {
    mockFetchOnce(submission);

    const res = await submitClip(
      "camp_1",
      { clip_url: "https://youtu.be/abc" },
      "idem-123",
      { token: "k2" },
    );

    expect(res).toEqual(submission);
    const { url, init } = lastCall();
    expect(url).toContain("/clipmarket/campaigns/camp_1/submit");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      clip_url: "https://youtu.be/abc",
    });
    expect(headers(init)["Idempotency-Key"]).toBe("idem-123");
    expect(headers(init)["x-api-key"]).toBe("k2");
  });
});

describe("reviewSubmission", () => {
  it("POSTs the review body to /clipmarket/submissions/{id}/review", async () => {
    mockFetchOnce(submission);

    const res = await reviewSubmission(
      "sub_1",
      { views: 1200, velocity_zscore: 2.1, engagement_rate: 0.08 },
      { token: "k3" },
    );

    expect(res).toEqual(submission);
    const { url, init } = lastCall();
    expect(url).toContain("/clipmarket/submissions/sub_1/review");
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body.views).toBe(1200);
    expect(body.velocity_zscore).toBe(2.1);
    expect(body.engagement_rate).toBe(0.08);
  });

  it("throws ApiError when the submission is missing (404)", async () => {
    mockFetchOnce({ message: "not found" }, false, 404);
    await expect(
      reviewSubmission("missing", { views: 0 }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});
