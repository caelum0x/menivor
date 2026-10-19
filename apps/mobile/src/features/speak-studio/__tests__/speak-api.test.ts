/**
 * Unit tests for the Speak Studio API client this feature owns in `lib/speak.ts`:
 * generateSpeak + getSpeakGeneration + listSpeakProviders. `fetch` is mocked
 * IN-TEST only — product code always hits the real ReelForge API. These assert
 * the endpoint, method, body, owner token, idempotency-key wiring, defensive
 * normalization of the providers payload, and the 402/404 error surfaces.
 */

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import {
  generateSpeak,
  getSpeakGeneration,
  listSpeakProviders,
  type SpeakGeneration,
} from "@/lib/speak";
import { ApiError } from "@/src/shared/api";
import { JobState } from "@/lib/types";

type FetchArgs = Parameters<typeof fetch>;

function mockFetchOnce(data: unknown, ok = true, status = 200): void {
  (global.fetch as Mock).mockResolvedValueOnce({
    ok,
    status,
    text: async () =>
      JSON.stringify(ok ? { status, data } : { status, message: data }),
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

const SNAPSHOT: SpeakGeneration = {
  generation_id: "gen_1",
  state: JobState.Processing,
  progress: 0,
  talking_video_key: "",
  result_url: "",
  provider: "musetalk",
  license_class: "commercial",
  error: "",
  retry_eligible: false,
};

beforeEach(() => {
  global.fetch = vi.fn() as unknown as typeof fetch;
});

afterEach(() => {
  vi.resetAllMocks();
});

describe("generateSpeak", () => {
  it("POSTs /generation/speak/generate with the body, token, and idempotency key", async () => {
    mockFetchOnce(SNAPSHOT);

    const res = await generateSpeak(
      { image_key: "uploads/a.jpg", audio_key: "uploads/v.m4a", provider: "musetalk" },
      { token: "k1", idempotencyKey: "idem-1" },
    );

    expect(res).toEqual(SNAPSHOT);
    const { url, init } = lastCall();
    expect(url).toContain("/generation/speak/generate");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      image_key: "uploads/a.jpg",
      audio_key: "uploads/v.m4a",
      provider: "musetalk",
    });
    expect(headers(init)["x-api-key"]).toBe("k1");
    expect(headers(init)["Idempotency-Key"]).toBe("idem-1");
    expect(headers(init)["Content-Type"]).toBe("application/json");
  });

  it("surfaces a 402 as an ApiError on insufficient credits", async () => {
    mockFetchOnce("insufficient credits", false, 402);
    let caught: unknown;
    try {
      await generateSpeak(
        { image_key: "uploads/a.jpg", audio_key: "uploads/v.m4a" },
        { token: "k1" },
      );
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(402);
  });
});

describe("getSpeakGeneration", () => {
  it("GETs /generation/speak/generations/{id} with the owner token", async () => {
    mockFetchOnce({ ...SNAPSHOT, state: JobState.Complete, result_url: "https://cdn/x.mp4" });

    const res = await getSpeakGeneration("gen_1", { token: "k1" });

    expect(res.state).toBe(JobState.Complete);
    const { url, init } = lastCall();
    expect(url).toContain("/generation/speak/generations/gen_1");
    expect(init.method ?? "GET").toBe("GET");
    expect(headers(init)["x-api-key"]).toBe("k1");
  });

  it("URL-encodes a generation id with unsafe characters", async () => {
    mockFetchOnce(SNAPSHOT);
    await getSpeakGeneration("a/b", { token: "k1" });
    expect(lastCall().url).toContain("/generation/speak/generations/a%2Fb");
  });

  it("surfaces a 404 as an ApiError for a foreign generation", async () => {
    mockFetchOnce("generation not found", false, 404);
    let caught: unknown;
    try {
      await getSpeakGeneration("gen_x", { token: "k1" });
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(404);
  });
});

describe("listSpeakProviders", () => {
  it("normalizes the capability payload and drops junk provider rows", async () => {
    mockFetchOnce({
      modes: ["image_audio_to_video", 5],
      runtime: "gpu_worker",
      providers: [
        {
          provider: "musetalk",
          capability: "lipsync",
          metering_unit: "second",
          license_class: "commercial",
          latency_band: "fast",
          available: true,
        },
        null,
        { capability: "no-provider-key" },
      ],
    });

    const res = await listSpeakProviders({ token: "k1" });

    expect(res.modes).toEqual(["image_audio_to_video"]);
    expect(res.runtime).toBe("gpu_worker");
    expect(res.providers).toHaveLength(1);
    expect(res.providers[0]!.provider).toBe("musetalk");
    expect(lastCall().url).toContain("/generation/speak/providers");
  });

  it("degrades a blank payload to empty lists", async () => {
    mockFetchOnce({});
    const res = await listSpeakProviders({ token: "k1" });
    expect(res.providers).toHaveLength(0);
    expect(res.modes).toHaveLength(0);
    expect(res.runtime).toBe("");
  });
});
