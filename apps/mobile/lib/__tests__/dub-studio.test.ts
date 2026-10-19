import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildDubRequest,
  createDubVideo,
  defaultEngine,
  dubCost,
  getDubVideo,
  isTerminalDub,
  languageLabel,
  listDubVideos,
  upsertDub,
  type DubOptions,
  type DubVideo,
} from "@/lib/dub-studio";

type FetchMock = ReturnType<typeof vi.fn>;
let fetchMock: FetchMock;

function respond(data: unknown, status = 200): void {
  fetchMock.mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(status < 300 ? { status, data } : { status, message: data }),
    headers: { get: () => null },
  });
}

function lastCall(): { url: string; init: RequestInit } {
  const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [string, RequestInit];
  return { url, init };
}

const OPTIONS: DubOptions = {
  available: true,
  engine: "sidecar",
  languages: [
    { code: "en", label: "English", voices: ["en-US-AriaNeural"] },
    { code: "es", label: "Spanish", voices: ["es-ES-ElviraNeural", "es-ES-AlvaroNeural"] },
  ],
  voice_engines: [
    { id: "edge", label: "Free voices", available: true, free: true },
    { id: "elevenlabs", label: "ElevenLabs", available: false, free: false },
  ],
  whisper_models: ["base"],
  default_whisper_model: "base",
  translation: "google",
  costs: { free: 0, premium: 5 },
  max_seconds: 600,
  max_bytes: 500_000_000,
};

function dub(overrides: Partial<DubVideo> = {}): DubVideo {
  return {
    dub_id: "d1",
    state: "processing",
    progress: 10,
    source_key: "uploads/a.mp4",
    source_language: "en",
    target_language: "es",
    voice_engine: "edge",
    voice: "",
    free: true,
    credits_cost: 0,
    refunded: false,
    video_key: "",
    video_url: "",
    subtitles: [],
    error: "",
    created_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("dub studio client", () => {
  it("creates a dub with the caller's key", async () => {
    respond(dub());
    await createDubVideo(
      { video_key: "uploads/a.mp4", source_language: "en", target_language: "es", voice_engine: "edge" },
      { token: "k_user" },
    );
    const { url, init } = lastCall();
    expect(url).toMatch(/\/dub\/videos$/);
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["x-api-key"]).toBe("k_user");
    expect(JSON.parse(String(init.body))).toMatchObject({ video_key: "uploads/a.mp4", target_language: "es" });
  });

  it("lists dubs with a clamped limit and tolerates a missing array", async () => {
    respond({ dubs: [dub()] });
    expect(await listDubVideos(500)).toHaveLength(1);
    expect(lastCall().url).toMatch(/\/dub\/videos\?limit=50$/);
    respond({});
    expect(await listDubVideos()).toEqual([]);
  });

  it("polls one dub by encoded id", async () => {
    respond(dub({ state: "complete" }));
    const polled = await getDubVideo("d/1");
    expect(polled.state).toBe("complete");
    expect(lastCall().url).toMatch(/\/dub\/videos\/d%2F1$/);
  });
});

describe("dub studio helpers", () => {
  const draft = { videoKey: "uploads/a.mp4", sourceLanguage: "en", targetLanguage: "es", engine: "edge" as const, voice: "" };

  it("builds a valid request", () => {
    expect(buildDubRequest(draft, OPTIONS)).toEqual({
      ok: true,
      body: { video_key: "uploads/a.mp4", source_language: "en", target_language: "es", voice_engine: "edge" },
    });
    const withVoice = buildDubRequest({ ...draft, voice: "es-ES-AlvaroNeural" }, OPTIONS);
    expect(withVoice.ok && withVoice.body.voice).toBe("es-ES-AlvaroNeural");
  });

  it("rejects incomplete or impossible drafts with readable errors", () => {
    expect(buildDubRequest({ ...draft, videoKey: " " }, OPTIONS)).toMatchObject({ ok: false });
    expect(buildDubRequest({ ...draft, targetLanguage: "en" }, OPTIONS)).toEqual({
      ok: false,
      error: "Pick a different language to dub into.",
    });
    expect(buildDubRequest({ ...draft, targetLanguage: "" }, OPTIONS)).toMatchObject({ ok: false });
    expect(buildDubRequest({ ...draft, engine: "elevenlabs" }, OPTIONS)).toMatchObject({ ok: false });
    expect(buildDubRequest(draft, { ...OPTIONS, available: false })).toEqual({
      ok: false,
      error: "Dubbing is not set up on this server yet.",
    });
  });

  it("prices by engine and prefers a free engine", () => {
    expect(dubCost(OPTIONS, "edge")).toBe(0);
    expect(dubCost(OPTIONS, "elevenlabs")).toBe(5);
    expect(defaultEngine(OPTIONS.voice_engines)).toBe("edge");
    expect(defaultEngine([{ id: "elevenlabs", label: "", available: false, free: false }])).toBe("");
  });

  it("tracks terminal states, labels and history without mutation", () => {
    expect(isTerminalDub({ state: "processing" })).toBe(false);
    expect(isTerminalDub({ state: "failed" })).toBe(true);
    expect(languageLabel(OPTIONS.languages, "es")).toBe("Spanish");
    expect(languageLabel(OPTIONS.languages, "zz")).toBe("zz");
    const list = [dub()];
    const updated = upsertDub(list, dub({ state: "complete" }));
    expect(updated[0]?.state).toBe("complete");
    expect(list[0]?.state).toBe("processing");
    expect(upsertDub(list, dub({ dub_id: "d2" })).map((d) => d.dub_id)).toEqual(["d2", "d1"]);
  });
});
