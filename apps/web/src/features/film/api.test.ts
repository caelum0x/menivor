import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createProject,
  getProject,
  newIdempotencyKey,
  planFilm,
} from "./api";

/** Build a minimal Response-like object for the shared apiRequest transport. */
function jsonResponse(
  body: unknown,
  init: { ok?: boolean; status?: number } = {},
): Response {
  const ok = init.ok ?? true;
  const status = init.status ?? (ok ? 200 : 400);
  return {
    ok,
    status,
    statusText: ok ? "OK" : "Error",
    text: async () => JSON.stringify(body),
    headers: { get: () => null },
  } as unknown as Response;
}

function mockFetch() {
  const fn = vi.fn();
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const CHARACTER = { character_id: "mara", name: "Mara" };
const BEATS = [{ scene_id: "s1", summary: "Mara wakes to a ringing phone" }];

describe("planFilm", () => {
  it("POSTs /film/plan with the plan body and returns the unwrapped plan", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          total_runtime_s: 12.5,
          node_order: ["shot_1"],
          shots: [
            {
              shot_id: "shot_1",
              scene_id: "s1",
              order: 1,
              role: "establishing",
              camera_motion: "static",
              duration_s: 3.2,
              prompt: "Mara, red coat, wakes",
              seed: 42,
            },
          ],
        },
      }),
    );

    const plan = await planFilm(
      { beats: BEATS, character: CHARACTER, total_shots: 8 },
      { token: "tok" },
    );

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/film/plan");
    expect(init.method).toBe("POST");
    expect(init.headers["x-api-key"]).toBe("tok");
    expect(JSON.parse(init.body)).toEqual({
      beats: BEATS,
      character: CHARACTER,
      total_shots: 8,
    });
    expect(plan.total_runtime_s).toBe(12.5);
    expect(plan.shots[0]!.seed).toBe(42);
  });
});

describe("createProject", () => {
  it("POSTs /film/projects with the body + Idempotency-Key and returns the summary", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          id: "proj-1",
          title: "Midnight Courier",
          status: "planned",
          shot_count: 8,
          total_runtime_s: 26.4,
        },
      }),
    );

    const summary = await createProject(
      { title: "Midnight Courier", beats: BEATS, character: CHARACTER, total_shots: 8 },
      { token: "tok", idempotencyKey: "idem-123" },
    );

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/film/projects");
    expect(init.method).toBe("POST");
    expect(init.headers["Idempotency-Key"]).toBe("idem-123");
    expect(init.headers["x-api-key"]).toBe("tok");
    expect(JSON.parse(init.body)).toEqual({
      title: "Midnight Courier",
      beats: BEATS,
      character: CHARACTER,
      total_shots: 8,
    });
    expect(summary.id).toBe("proj-1");
    expect(summary.shot_count).toBe(8);
    expect(summary.total_runtime_s).toBe(26.4);
  });

  it("propagates a 503 when film persistence is unavailable", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { message: "film persistence unavailable" },
        { ok: false, status: 503 },
      ),
    );

    await expect(
      createProject(
        { beats: BEATS, character: CHARACTER },
        { token: "tok", idempotencyKey: "idem-x" },
      ),
    ).rejects.toThrow(/film persistence unavailable/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("getProject", () => {
  it("GETs /film/projects/{id} (encoded) and returns the project with shots", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          id: "proj 1/x",
          title: "Midnight Courier",
          status: "planned",
          total_runtime_s: 26.4,
          shots: [
            {
              shot_id: "shot_1",
              order: 1,
              role: "establishing",
              camera_motion: "static",
              duration_ms: 3200,
              prompt: "Mara, red coat, wakes",
              seed: 42,
              status: "pending",
            },
          ],
        },
      }),
    );

    const project = await getProject("proj 1/x", { token: "tok" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/film/projects/proj%201%2Fx");
    expect(init.method).toBe("GET");
    expect(project.shots).toHaveLength(1);
    expect(project.shots[0]!.duration_ms).toBe(3200);
    expect(project.shots[0]!.status).toBe("pending");
  });

  it("propagates a 404 when the project is not found", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ message: "project not found" }, { ok: false, status: 404 }),
    );

    await expect(getProject("missing", { token: "tok" })).rejects.toThrow(
      /project not found/,
    );
  });
});

describe("newIdempotencyKey", () => {
  it("returns a non-empty string", () => {
    expect(newIdempotencyKey().length).toBeGreaterThan(0);
  });
});
