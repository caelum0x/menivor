/**
 * Unit tests for the read-only earnings client `lib/earnings.ts`:
 * getWalletBalance + getWalletActivity. Assert endpoint / method / query wiring
 * and envelope unwrapping. `fetch` is mocked IN-TEST only — product code always
 * hits the real API.
 */

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import {
  getWalletActivity,
  getWalletBalance,
  type WalletActivityEntry,
  type WalletBalance,
} from "@/lib/earnings";
import { ApiError } from "@/src/shared/api";

type FetchArgs = Parameters<typeof fetch>;

const balance: WalletBalance = {
  account_id: "acct_1",
  currency: "USD",
  available_micros: 42_000_000,
  reserved_micros: 0,
  available_usd: "$42.00",
  reserved_usd: "$0.00",
};

const entry: WalletActivityEntry = {
  id: 9,
  entry_type: "credit",
  reason: "clip payout",
  available_delta: 3_600_000,
  available_after_usd: "$42.00",
  job_id: null,
  created_at: "2026-08-19T00:00:00Z",
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

describe("getWalletBalance", () => {
  it("GETs /wallet and unwraps the balance snapshot", async () => {
    mockFetchOnce(balance);

    const res = await getWalletBalance({ token: "k1" });

    expect(res).toEqual(balance);
    const { url, init } = lastCall();
    expect(url).toContain("/wallet");
    expect(init.method ?? "GET").toBe("GET");
    expect((init.headers as Record<string, string>)["x-api-key"]).toBe("k1");
    expect(init.body).toBeUndefined();
  });

  it("throws ApiError on a non-2xx response", async () => {
    mockFetchOnce({ message: "boom" }, false, 503);
    await expect(getWalletBalance()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("getWalletActivity", () => {
  it("GETs /wallet/activity with limit + offset and unwraps {activity}", async () => {
    mockFetchOnce({ activity: [entry] });

    const res = await getWalletActivity(25, 50, { token: "k2" });

    expect(res).toEqual([entry]);
    const { url, init } = lastCall();
    expect(url).toContain("/wallet/activity?limit=25&offset=50");
    expect(init.method ?? "GET").toBe("GET");
  });

  it("defaults to limit=50 & offset=0 and clamps out-of-range input", async () => {
    mockFetchOnce({ activity: [] });
    await getWalletActivity();
    expect(lastCall().url).toContain("limit=50&offset=0");

    mockFetchOnce({ activity: [] });
    await getWalletActivity(9999, -5);
    expect(lastCall().url).toContain("limit=200&offset=0");
  });

  it("tolerates a bare-array response", async () => {
    mockFetchOnce([entry]);
    const res = await getWalletActivity(10, 0);
    expect(res).toEqual([entry]);
  });

  it("degrades to [] when the payload omits the activity array", async () => {
    mockFetchOnce({});
    const res = await getWalletActivity();
    expect(res).toEqual([]);
  });
});
