/**
 * Unit tests for the character-identity API client this feature owns in
 * `lib/character-identity.ts`: getCharacter + buildCharacterShotPrompt +
 * listCharacterReferences + addCharacterReference + trainCharacter +
 * deleteCharacter. `fetch` is mocked IN-TEST only — product code always hits the
 * real ReelForge API. These assert endpoint/method/body/token wiring, defensive
 * unwrapping of the references list, and the owner-scoped 404 surface.
 */

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import {
  addCharacterReference,
  buildCharacterShotPrompt,
  deleteCharacter,
  getCharacter,
  listCharacterReferences,
  trainCharacter,
  type CharacterDetail,
  type CharacterReference,
  type ShotPrompt,
  type TrainResult,
} from "@/lib/character-identity";
import { ApiError } from "@/src/shared/api";

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

beforeEach(() => {
  global.fetch = vi.fn() as unknown as typeof fetch;
});

afterEach(() => {
  vi.resetAllMocks();
});

describe("getCharacter", () => {
  it("GETs /characters/{id} with the owner token", async () => {
    const detail: CharacterDetail = {
      id: "c1",
      name: "Mara",
      descriptors: ["red hair"],
      reference_images: ["uploads/a.jpg"],
      style: "cinematic",
      lora_ref: "",
      identity_key: "idk_1",
    };
    mockFetchOnce(detail);

    const res = await getCharacter("c1", { token: "k1" });

    expect(res).toEqual(detail);
    const { url, init } = lastCall();
    expect(url).toContain("/characters/c1");
    expect(init.method ?? "GET").toBe("GET");
    expect(headers(init)["x-api-key"]).toBe("k1");
  });

  it("surfaces a 404 as an ApiError for a foreign character", async () => {
    mockFetchOnce("character not found", false, 404);
    let caught: unknown;
    try {
      await getCharacter("c_x", { token: "k1" });
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(404);
  });
});

describe("buildCharacterShotPrompt", () => {
  it("POSTs /characters/{id}/shot-prompt with the action body", async () => {
    const prompt: ShotPrompt = {
      prompt: "Mara smiles",
      negative_prompt: "blurry",
      seed: 7,
      reference_images: ["uploads/a.jpg"],
      lora_ref: "",
    };
    mockFetchOnce(prompt);

    const res = await buildCharacterShotPrompt(
      "c1",
      { action: "smiles warmly", shot_index: 2, scene: "cafe" },
      { token: "k1" },
    );

    expect(res).toEqual(prompt);
    const { url, init } = lastCall();
    expect(url).toContain("/characters/c1/shot-prompt");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      action: "smiles warmly",
      shot_index: 2,
      scene: "cafe",
    });
  });
});

describe("listCharacterReferences", () => {
  it("unwraps the { references } envelope", async () => {
    const refs: CharacterReference[] = [
      {
        id: "r1",
        r2_key: "uploads/a.jpg",
        role: "sheet",
        content_type: "image/jpeg",
        width: 512,
        height: 512,
      },
    ];
    mockFetchOnce({ references: refs });

    const res = await listCharacterReferences("c1", { token: "k1" });

    expect(res).toHaveLength(1);
    expect(res[0]!.r2_key).toBe("uploads/a.jpg");
    expect(lastCall().url).toContain("/characters/c1/references");
  });

  it("degrades a blank payload to an empty list", async () => {
    mockFetchOnce({});
    const res = await listCharacterReferences("c1", { token: "k1" });
    expect(res).toHaveLength(0);
  });
});

describe("addCharacterReference", () => {
  it("POSTs /characters/{id}/references with the r2_key body", async () => {
    const ref: CharacterReference = {
      id: "r1",
      r2_key: "uploads/a.jpg",
      role: "sheet",
      content_type: "image/jpeg",
      width: 0,
      height: 0,
    };
    mockFetchOnce(ref);

    const res = await addCharacterReference(
      "c1",
      { r2_key: "uploads/a.jpg", role: "sheet", content_type: "image/jpeg" },
      { token: "k1" },
    );

    expect(res).toEqual(ref);
    const { url, init } = lastCall();
    expect(url).toContain("/characters/c1/references");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      r2_key: "uploads/a.jpg",
      role: "sheet",
      content_type: "image/jpeg",
    });
  });
});

describe("trainCharacter", () => {
  it("POSTs /characters/{id}/train and returns the job handle", async () => {
    const result: TrainResult = {
      job_id: "job_1",
      state: "processing",
      character_id: "c1",
    };
    mockFetchOnce(result);

    const res = await trainCharacter("c1", { steps: 800 }, { token: "k1" });

    expect(res).toEqual(result);
    const { url, init } = lastCall();
    expect(url).toContain("/characters/c1/train");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ steps: 800 });
  });

  it("surfaces a 400 when no references are bound yet", async () => {
    mockFetchOnce("at least 1 bound reference image(s) are required", false, 400);
    let caught: unknown;
    try {
      await trainCharacter("c1", {}, { token: "k1" });
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(400);
  });
});

describe("deleteCharacter", () => {
  it("DELETEs /characters/{id} with the owner token", async () => {
    mockFetchOnce({ deleted: true, id: "c1" });

    const res = await deleteCharacter("c1", { token: "k1" });

    expect(res).toEqual({ deleted: true, id: "c1" });
    const { url, init } = lastCall();
    expect(url).toContain("/characters/c1");
    expect(init.method).toBe("DELETE");
    expect(headers(init)["x-api-key"]).toBe("k1");
  });
});
