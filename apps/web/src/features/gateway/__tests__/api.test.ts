import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  bpsToPercent,
  createKey,
  listKeys,
  microsToUsd,
  quoteKey,
  revokeKey,
  usdToMicros,
} from "../api";

/** Build a minimal `fetch` Response yielding an MPT `{ data }` envelope. */
function envelope(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "OK",
    headers: { get: () => null },
    text: async () => JSON.stringify({ status, data }),
  } as unknown as Response;
}

describe("gateway api client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("listKeys GETs /gateway/keys and unwraps data", async () => {
    fetchMock.mockResolvedValueOnce(
      envelope({
        keys: [
          {
            id: "k1",
            label: "Acme",
            daily_cap_micros: 1_000_000,
            markup_bps: 2000,
            min_fee_micros: 0,
            disabled: false,
          },
        ],
      }),
    );

    const res = await listKeys({ token: "t" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/gateway/keys");
    expect(init.method).toBe("GET");
    expect(res.keys[0]!.label).toBe("Acme");
  });

  it("createKey POSTs the body and sends the Idempotency-Key header", async () => {
    fetchMock.mockResolvedValueOnce(
      envelope({
        id: "k2",
        label: "New",
        daily_cap_micros: 5_000_000,
        markup_bps: 1500,
        min_fee_micros: 10_000,
        disabled: false,
        secret: "sk_live_once",
      }),
    );

    const res = await createKey(
      {
        label: "New",
        daily_cap_micros: 5_000_000,
        markup_bps: 1500,
        min_fee_micros: 10_000,
      },
      { token: "tok", idempotencyKey: "idem-77" },
    );

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/gateway/keys");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      label: "New",
      daily_cap_micros: 5_000_000,
      markup_bps: 1500,
      min_fee_micros: 10_000,
    });
    expect(init.headers["Idempotency-Key"]).toBe("idem-77");
    expect(init.headers["x-api-key"]).toBe("tok");
    expect(res.secret).toBe("sk_live_once");
  });

  it("revokeKey POSTs the encoded revoke path with no body", async () => {
    fetchMock.mockResolvedValueOnce(
      envelope({
        id: "k 3",
        label: "Gone",
        daily_cap_micros: 0,
        markup_bps: 0,
        min_fee_micros: 0,
        disabled: true,
      }),
    );

    const res = await revokeKey("k 3", { token: "t" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/gateway/keys/k%203/revoke");
    expect(init.method).toBe("POST");
    // No JSON body on a pure state-transition POST.
    expect(init.body).toBeUndefined();
    expect(res.disabled).toBe(true);
  });

  it("quoteKey POSTs base_cost_micros to the encoded quote path", async () => {
    fetchMock.mockResolvedValueOnce(
      envelope({
        base_cost_micros: 1_000_000,
        customer_price_micros: 1_200_000,
        spent_today_micros: 0,
        remaining_micros: 3_800_000,
        would_allow: true,
      }),
    );

    const res = await quoteKey("k1", 1_000_000, { token: "t" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/gateway/keys/k1/quote");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      base_cost_micros: 1_000_000,
    });
    expect(res.customer_price_micros).toBe(1_200_000);
    expect(res.would_allow).toBe(true);
  });

  it("propagates API errors as thrown ApiError", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: "Not Found",
      headers: { get: () => null },
      text: async () => JSON.stringify({ status: 404, message: "key not found" }),
    } as unknown as Response);

    await expect(revokeKey("missing", { token: "t" })).rejects.toThrow(
      /key not found/,
    );
  });

  it("money + rate helpers convert between display and wallet units", () => {
    expect(usdToMicros(1.5)).toBe(1_500_000);
    expect(microsToUsd(1_200_000)).toBe("$1.20");
    expect(bpsToPercent(2000)).toBe("20.0%");
  });
});
