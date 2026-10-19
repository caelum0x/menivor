/**
 * Unit tests for the Experiments API layer (`lib/experiments.ts`): create, get,
 * ingest-metrics, evaluate + the `parseHookRefs` helper. `fetch` is mocked
 * IN-TEST only — product code always talks to the real API.
 */

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import {
  MAX_HOOKS,
  MIN_HOOKS,
  createExperiment,
  evaluateExperiment,
  getExperiment,
  ingestMetrics,
  parseHookRefs,
  type Experiment,
} from "@/lib/experiments";
import { ApiError } from "@/src/shared/api";

type FetchArgs = Parameters<typeof fetch>;

const experiment: Experiment = {
  id: "exp_1",
  experiment_key: "launch_hooks",
  status: "running",
  body_ref: "body_v2",
  winner_variant_id: null,
  winner_hook_ref: null,
  variants: [
    {
      id: "v1",
      hook_ref: "POV you just...",
      views: 300,
      completion_rate: 0.6,
      avg_watch_frac: 0.5,
      rewatch_rate: 0.1,
      engagement_rate: 0.08,
    },
    {
      id: "v2",
      hook_ref: "Stop scrolling if...",
      views: 320,
      completion_rate: 0.4,
      avg_watch_frac: 0.35,
      rewatch_rate: 0.05,
      engagement_rate: 0.04,
    },
  ],
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

describe("createExperiment", () => {
  it("POSTs the key + hooks + body and unwraps the envelope", async () => {
    mockFetchOnce(experiment);

    const res = await createExperiment(
      { experiment_key: "launch_hooks", hook_refs: ["a", "b"], body_ref: "body_v2" },
      { token: "k1", idempotencyKey: "exp-launch_hooks" },
    );

    expect(res).toEqual(experiment);
    const { url, init } = lastCall();
    expect(url).toContain("/experiments");
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers["x-api-key"]).toBe("k1");
    expect(headers["Idempotency-Key"]).toBe("exp-launch_hooks");
    const body = JSON.parse(String(init.body));
    expect(body.experiment_key).toBe("launch_hooks");
    expect(body.hook_refs).toEqual(["a", "b"]);
    expect(body.body_ref).toBe("body_v2");
  });

  it("throws ApiError on a 422 (hook-count out of range)", async () => {
    mockFetchOnce({ message: "need 2..20 hooks" }, false, 422);
    await expect(
      createExperiment({ experiment_key: "x", hook_refs: ["only"] }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe("getExperiment", () => {
  it("GETs the experiment by key and unwraps the verdict", async () => {
    mockFetchOnce(experiment);

    const res = await getExperiment("launch_hooks", { token: "k2" });

    expect(res.variants).toHaveLength(2);
    const { url, init } = lastCall();
    expect(url).toContain("/experiments/launch_hooks");
    expect(init.method ?? "GET").toBe("GET");
    expect(init.body).toBeUndefined();
  });

  it("encodes the key into the path", async () => {
    mockFetchOnce(experiment);
    await getExperiment("a/b c");
    expect(lastCall().url).toContain("/experiments/a%2Fb%20c");
  });

  it("throws ApiError on a 404 (unknown key)", async () => {
    mockFetchOnce({ message: "not found" }, false, 404);
    await expect(getExperiment("nope")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("ingestMetrics", () => {
  it("POSTs a variant's retention snapshot to the variant path", async () => {
    mockFetchOnce({ id: "v1", hook_ref: "POV you just...", views: 300 });

    const res = await ingestMetrics(
      "launch_hooks",
      "v1",
      {
        views: 300,
        completion_rate: 0.6,
        avg_watch_frac: 0.5,
        rewatch_rate: 0.1,
        engagement_rate: 0.08,
      },
      { token: "k3" },
    );

    expect(res.id).toBe("v1");
    const { url, init } = lastCall();
    expect(url).toContain("/experiments/launch_hooks/variants/v1/metrics");
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body.views).toBe(300);
    expect(body.completion_rate).toBe(0.6);
  });
});

describe("evaluateExperiment", () => {
  it("POSTs to /evaluate and returns the persisted winner", async () => {
    mockFetchOnce({
      ...experiment,
      status: "conclusive",
      winner_variant_id: "v1",
      winner_hook_ref: "POV you just...",
    });

    const res = await evaluateExperiment("launch_hooks", { token: "k4" });

    expect(res.winner_variant_id).toBe("v1");
    expect(res.status).toBe("conclusive");
    const { url, init } = lastCall();
    expect(url).toContain("/experiments/launch_hooks/evaluate");
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
  });
});

describe("parseHookRefs", () => {
  it("parses one hook per line, trims, skips blanks and de-dupes", () => {
    const out = parseHookRefs("  POV you...  \n\nStop scrolling\nPOV you...\n  ");
    expect(out).toEqual(["POV you...", "Stop scrolling"]);
  });

  it("stays within the backend-accepted count bounds for real input", () => {
    const out = parseHookRefs("one\ntwo\nthree");
    expect(out.length).toBe(3);
    expect(out.length).toBe(MIN_HOOKS + 1);
    expect(out.length).toBe(MAX_HOOKS - 17);
  });
});
