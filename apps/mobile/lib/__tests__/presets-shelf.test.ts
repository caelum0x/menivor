/**
 * Unit tests for the mobile preset-shelf API client in `lib/presets-shelf.ts`:
 * listShelf + getTile + planPreset + quoteForPlan/quotePlan + startPlan +
 * recordRun + getRun + formatSeconds. `fetch` is mocked IN-TEST only — product
 * code always hits the real Menivor API. These assert endpoint/method/body/
 * token wiring and the two pricing routes (standard "jobs" vs AI-video
 * "generation/broll/generate" presets), mirroring
 * apps/web/src/features/presets-shelf/presets-shelf.test.ts.
 */

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import {
  formatSeconds,
  getRun,
  getTile,
  listShelf,
  planPreset,
  quoteForPlan,
  quotePlan,
  recordRun,
  startPlan,
  type PresetPlan,
  type PresetTile,
} from "@/lib/presets-shelf";
import { ApiError } from "@/src/shared/api";

type FetchArgs = Parameters<typeof fetch>;

function mockFetchOnce(data: unknown, ok = true, status = 200): void {
  (global.fetch as Mock).mockResolvedValueOnce({
    ok,
    status,
    text: async () => JSON.stringify(ok ? { status, data } : { status, message: data }),
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

const TILE: PresetTile = {
  id: "neon-drive",
  name: "Neon Drive",
  blurb: "A moody night-drive camera move",
  kind: "filter",
  credit_kind: "standard",
  credit_label: "Standard credits",
  inputs: ["subject"],
  preview: { loop_url: "https://cdn.example/neon.mp4", poster_url: "https://cdn.example/neon.jpg" },
  create_url: "/presets-gallery?use=neon-drive",
  target_seconds: 180,
};

const MODEL_TILE: PresetTile = {
  ...TILE,
  id: "animate-photo",
  kind: "model",
  credit_kind: "ai_video",
  credit_label: "AI-video credits",
  inputs: ["subject", "image"],
};

beforeEach(() => {
  global.fetch = vi.fn() as unknown as typeof fetch;
});

afterEach(() => {
  vi.resetAllMocks();
});

describe("listShelf", () => {
  it("GETs /presets/shelf and unwraps the presets envelope", async () => {
    mockFetchOnce({ presets: [TILE] });
    const res = await listShelf();
    expect(res).toEqual([TILE]);
    expect(lastCall().url).toContain("/presets/shelf");
  });

  it("degrades a blank payload to an empty list", async () => {
    mockFetchOnce({});
    const res = await listShelf();
    expect(res).toHaveLength(0);
  });
});

describe("getTile", () => {
  it("GETs /presets/shelf/{id}", async () => {
    mockFetchOnce(TILE);
    const res = await getTile("neon-drive", { token: "k1" });
    expect(res).toEqual(TILE);
    const { url, init } = lastCall();
    expect(url).toContain("/presets/shelf/neon-drive");
    expect(headers(init)["x-api-key"]).toBe("k1");
  });

  it("surfaces a 404 as an ApiError for an unknown preset", async () => {
    mockFetchOnce("preset not found", false, 404);
    let caught: unknown;
    try {
      await getTile("ghost");
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(404);
  });

  it("encodes a preset id with special characters", async () => {
    mockFetchOnce(TILE);
    await getTile("a b/c");
    expect(lastCall().url).toContain("/presets/shelf/a%20b%2Fc");
  });
});

describe("planPreset", () => {
  it("POSTs /presets/shelf/{id}/plan with the typed subject", async () => {
    const plan: PresetPlan = { route: "jobs", body: { params: { video_subject: "espresso" } }, preset_id: "neon-drive" };
    mockFetchOnce(plan);

    const res = await planPreset("neon-drive", { subject: "espresso" }, { token: "k1" });

    expect(res).toEqual(plan);
    const { url, init } = lastCall();
    expect(url).toContain("/presets/shelf/neon-drive/plan");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ subject: "espresso" });
  });

  it("includes an image_key when the preset animates a photo", async () => {
    const plan: PresetPlan = { route: "generation/broll/generate", body: {}, preset_id: "animate-photo" };
    mockFetchOnce(plan);

    await planPreset("animate-photo", { subject: "my trip", image_key: "uploads/a.jpg" }, { token: "k1" });

    expect(JSON.parse(String(lastCall().init.body))).toEqual({
      subject: "my trip",
      image_key: "uploads/a.jpg",
    });
  });

  it("surfaces a 400 for an empty subject", async () => {
    mockFetchOnce("type a topic or paste a link", false, 400);
    let caught: unknown;
    try {
      await planPreset("neon-drive", { subject: "" });
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(400);
  });
});

describe("quoteForPlan", () => {
  it("prices a standard 'jobs' plan via /jobs/quote", async () => {
    mockFetchOnce({ total: { standard: 3 }, affordable: true });

    const res = await quoteForPlan({ route: "jobs", body: { params: {} } }, false, { token: "k1" });

    expect(res).toEqual({ credits: 3, affordable: true });
    const { url, init } = lastCall();
    expect(url).toContain("/jobs/quote");
    expect(url).not.toContain("/jobs/quote/preset");
    expect(init.method).toBe("POST");
  });

  it("prices an AI-video model plan via /jobs/quote/preset, keyed by animate_image", async () => {
    mockFetchOnce({ total: { ai_video: 12 }, affordable: false, route: { model_id: "kling-v2" } });

    const res = await quoteForPlan({ route: "generation/broll/generate", body: {} }, true, { token: "k1" });

    expect(res).toEqual({ credits: 12, affordable: false, route: "kling-v2" });
    const { url, init } = lastCall();
    expect(url).toContain("/jobs/quote/preset");
    expect(JSON.parse(String(init.body))).toMatchObject({ preset_sku: "animate_image", tier: "draft" });
  });

  it("keys a text-to-video model plan as text_to_video, not animate_image", async () => {
    mockFetchOnce({ total: { ai_video: 8 }, affordable: true });

    await quoteForPlan({ route: "generation/broll/generate", body: {} }, false, { token: "k1" });

    expect(JSON.parse(String(lastCall().init.body))).toMatchObject({ preset_sku: "text_to_video" });
  });
});

describe("quotePlan", () => {
  it("routes a model tile that needs an image through the animate_image quote", async () => {
    mockFetchOnce({ total: { ai_video: 12 }, affordable: true });
    const plan: PresetPlan = { route: "generation/broll/generate", body: {}, preset_id: MODEL_TILE.id };

    await quotePlan(MODEL_TILE, plan, { token: "k1" });

    expect(JSON.parse(String(lastCall().init.body))).toMatchObject({ preset_sku: "animate_image" });
  });

  it("routes a standard filter tile through /jobs/quote", async () => {
    mockFetchOnce({ total: { standard: 2 }, affordable: true });
    const plan: PresetPlan = { route: "jobs", body: { params: {} }, preset_id: TILE.id };

    await quotePlan(TILE, plan, { token: "k1" });

    expect(lastCall().url).toContain("/jobs/quote");
  });
});

describe("startPlan", () => {
  it("POSTs /jobs and returns job_id for a standard plan", async () => {
    mockFetchOnce({ job_id: "job_1" });
    const res = await startPlan({ route: "jobs", body: { params: {} } }, { token: "k1", idempotencyKey: "idem-1" });
    expect(res).toBe("job_1");
    const { url, init } = lastCall();
    expect(url).toContain("/jobs");
    expect(url).not.toContain("quote");
    expect(headers(init)["Idempotency-Key"]).toBe("idem-1");
  });

  it("POSTs /generation/broll/generate and falls back across id fields", async () => {
    mockFetchOnce({ generation_id: "gen_1" });
    const res = await startPlan({ route: "generation/broll/generate", body: {} }, { token: "k1" });
    expect(res).toBe("gen_1");
    expect(lastCall().url).toContain("/generation/broll/generate");
  });

  it("falls back to job_id then id when generation_id is absent", async () => {
    mockFetchOnce({ job_id: "job_2" });
    expect(await startPlan({ route: "generation/broll/generate", body: {} })).toBe("job_2");
    mockFetchOnce({ id: "id_3" });
    expect(await startPlan({ route: "generation/broll/generate", body: {} })).toBe("id_3");
  });
});

describe("recordRun", () => {
  it("POSTs /presets/shelf/{id}/runs with the job id and open time", async () => {
    mockFetchOnce({ job_id: "job_1", preset_id: "neon-drive", opened_at: "2026-10-18T00:00:00Z" });

    const res = await recordRun("neon-drive", { job_id: "job_1", opened_at: "2026-10-18T00:00:00Z" }, { token: "k1" });

    expect(res).toMatchObject({ job_id: "job_1" });
    expect(lastCall().url).toContain("/presets/shelf/neon-drive/runs");
  });
});

describe("getRun", () => {
  it("GETs /presets/runs/{job_id} and returns the timing view", async () => {
    mockFetchOnce({
      job_id: "job_1",
      preset_id: "neon-drive",
      seconds_to_result: 42,
      target_seconds: 180,
      within_target: true,
    });

    const res = await getRun("job_1", { token: "k1" });

    expect(res.seconds_to_result).toBe(42);
    expect(lastCall().url).toContain("/presets/runs/job_1");
  });

  it("surfaces a foreign job id as a 404 ApiError", async () => {
    mockFetchOnce("run not found", false, 404);
    let caught: unknown;
    try {
      await getRun("not-mine");
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(404);
  });
});

describe("formatSeconds", () => {
  it("formats sub-minute durations as seconds only", () => {
    expect(formatSeconds(48)).toBe("48 s");
  });

  it("formats minute-plus durations as 'm min s s'", () => {
    expect(formatSeconds(134)).toBe("2 min 14 s");
  });

  it("clamps a negative duration to zero", () => {
    expect(formatSeconds(-5)).toBe("0 s");
  });
});
