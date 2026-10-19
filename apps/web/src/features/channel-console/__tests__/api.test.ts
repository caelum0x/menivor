import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createExperiment,
  getExperiment,
  listChannels,
  listScheduled,
  schedulePost,
} from "../api";

/** Build a minimal `fetch` Response that yields an MPT `{ data }` envelope. */
function envelope(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "OK",
    headers: { get: () => null },
    text: async () => JSON.stringify({ status, data }),
  } as unknown as Response;
}

describe("channel-console api client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("listChannels GETs /me/connections and returns the bare data array", async () => {
    fetchMock.mockResolvedValueOnce(
      envelope([
        {
          provider: "tiktok",
          external_account_id: "acme",
          connected: true,
          status: "connected",
          scopes: "video.upload",
        },
      ]),
    );

    const res = await listChannels({ token: "t" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/me/connections");
    expect(init.method ?? "GET").toBe("GET");
    expect(res[0]!.provider).toBe("tiktok");
    expect(res[0]!.external_account_id).toBe("acme");
  });

  it("schedulePost POSTs /jobs/{id}/schedule with platforms + the idempotency key", async () => {
    fetchMock.mockResolvedValueOnce(
      envelope({
        id: "s1",
        job_id: "job_1",
        platforms: ["tiktok"],
        scheduled_at: "2026-01-01T00:00:00+00:00",
        status: "pending",
      }),
    );

    const res = await schedulePost(
      "job_1",
      { platforms: ["tiktok"], scheduled_at: "2026-01-01T00:00:00.000Z" },
      { token: "tok", idempotencyKey: "idem-123" },
    );

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/jobs/job_1/schedule");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      platforms: ["tiktok"],
      scheduled_at: "2026-01-01T00:00:00.000Z",
    });
    expect(init.headers["Idempotency-Key"]).toBe("idem-123");
    expect(init.headers["x-api-key"]).toBe("tok");
    expect(res.status).toBe("pending");
  });

  it("listScheduled GETs /me/scheduled and returns the bare data array", async () => {
    fetchMock.mockResolvedValueOnce(envelope([]));

    const res = await listScheduled({ token: "t" });

    expect(fetchMock.mock.calls[0]![0]).toContain("/me/scheduled");
    expect(res).toEqual([]);
  });

  it("createExperiment POSTs /experiments with hook_refs + an idempotency key", async () => {
    fetchMock.mockResolvedValueOnce(
      envelope({
        id: "exp1",
        experiment_key: "launch",
        status: "running",
        body_ref: "",
        winner_variant_id: null,
        winner_hook_ref: null,
        variants: [],
      }),
    );

    await createExperiment(
      { experiment_key: "launch", hook_refs: ["hook_a", "hook_b"] },
      { token: "tok", idempotencyKey: "idem-9" },
    );

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/experiments");
    expect(init.method).toBe("POST");
    expect(init.headers["Idempotency-Key"]).toBe("idem-9");
    expect(JSON.parse(init.body as string).hook_refs).toHaveLength(2);
  });

  it("getExperiment GETs the url-encoded /experiments/{key} path", async () => {
    fetchMock.mockResolvedValueOnce(
      envelope({
        id: "exp1",
        experiment_key: "exp 1",
        status: "settled",
        body_ref: "",
        winner_variant_id: null,
        winner_hook_ref: null,
        variants: [],
      }),
    );

    await getExperiment("exp 1", { token: "t" });

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/experiments/exp%201");
  });

  it("propagates API errors as thrown ApiError", async () => {
    // Error envelopes carry `message` at the top level, not inside `data`.
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      headers: { get: () => null },
      text: async () => JSON.stringify({ status: 500, message: "boom" }),
    } as unknown as Response);

    await expect(listChannels({ token: "t" })).rejects.toThrow(/boom/);
  });
});
