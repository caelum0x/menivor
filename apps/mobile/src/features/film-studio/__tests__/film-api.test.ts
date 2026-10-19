/**
 * Unit tests for the Wave-2 Film Studio API additions this feature owns in
 * `lib/film.ts`: createFilmProject + getFilmProject. `fetch` is mocked IN-TEST
 * only — product code always hits the real ReelForge API. These assert the
 * endpoint, method, body, owner token, and idempotency-key wiring, plus the
 * 503 (no DB) and 404 (non-owner) error surfaces.
 */

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import {
  createFilmProject,
  getFilmProject,
  type CreateProjectBody,
  type FilmProject,
  type FilmProjectSummary,
} from "@/lib/film";
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

const BODY: CreateProjectBody = {
  title: "Neon Heist",
  beats: [{ scene_id: "s1", summary: "Break in" }],
  character: { character_id: "lead_01", name: "Mara" },
  total_shots: 8,
};

beforeEach(() => {
  global.fetch = vi.fn() as unknown as typeof fetch;
});

afterEach(() => {
  vi.resetAllMocks();
});

describe("createFilmProject", () => {
  it("POSTs /film/projects with the body, token, and idempotency key", async () => {
    const summary: FilmProjectSummary = {
      id: "proj_1",
      title: "Neon Heist",
      status: "planned",
      shot_count: 8,
      total_runtime_s: 42.5,
    };
    mockFetchOnce(summary);

    const res = await createFilmProject(BODY, "idem-123", { token: "k1" });

    expect(res).toEqual(summary);
    const { url, init } = lastCall();
    expect(url).toContain("/film/projects");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual(BODY);
    expect(headers(init)["x-api-key"]).toBe("k1");
    expect(headers(init)["Idempotency-Key"]).toBe("idem-123");
    expect(headers(init)["Content-Type"]).toBe("application/json");
  });

  it("surfaces a 503 as an ApiError when persistence is unavailable", async () => {
    mockFetchOnce("film persistence unavailable", false, 503);
    let caught: unknown;
    try {
      await createFilmProject(BODY, "idem-1", { token: "k1" });
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(503);
  });
});

describe("getFilmProject", () => {
  it("GETs /film/projects/{id} with the owner token and unwraps shots", async () => {
    const project: FilmProject = {
      id: "proj_1",
      title: "Neon Heist",
      status: "planned",
      total_runtime_s: 42.5,
      shots: [
        {
          shot_id: "shot_1",
          order: 0,
          role: "establishing",
          camera_motion: "dolly_in",
          duration_ms: 3000,
          prompt: "Mara in the vault",
          seed: 7,
          status: "locked",
        },
      ],
    };
    mockFetchOnce(project);

    const res = await getFilmProject("proj_1", { token: "k1" });

    expect(res.shots).toHaveLength(1);
    const { url, init } = lastCall();
    expect(url).toContain("/film/projects/proj_1");
    expect(init.method ?? "GET").toBe("GET");
    expect(headers(init)["x-api-key"]).toBe("k1");
  });

  it("URL-encodes a project id containing unsafe characters", async () => {
    mockFetchOnce({ id: "a/b", title: "x", status: "planned", total_runtime_s: 0, shots: [] });
    await getFilmProject("a/b", { token: "k1" });
    expect(lastCall().url).toContain("/film/projects/a%2Fb");
  });

  it("surfaces a 404 as an ApiError for a non-owner project", async () => {
    mockFetchOnce("project not found", false, 404);
    let caught: unknown;
    try {
      await getFilmProject("proj_x", { token: "k1" });
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(404);
  });
});
