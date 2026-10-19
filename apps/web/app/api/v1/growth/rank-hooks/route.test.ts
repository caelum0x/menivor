import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Auth + rate-limit contract for POST /api/v1/growth/rank-hooks.
 *
 * The credential check is delegated to the Menivor API's `/me` (stubbed here via
 * a fake global fetch). TYPESAFE_API_KEY is unset so an allowed request takes
 * the heuristic path and never calls Jev.
 */

const VALID_KEYS: Record<string, string> = { "alice-key": "user-alice", "bob-key": "user-bob" };

let meCalls = 0;
let apiDown = false;

function fakeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = String(input);
  if (!url.endsWith("/me")) throw new Error(`unexpected fetch ${url}`);
  meCalls += 1;
  if (apiDown) return Promise.reject(new Error("connect ECONNREFUSED"));
  const headers = new Headers(init?.headers);
  const bearer = headers.get("authorization")?.replace(/^Bearer\s+/i, "");
  const key = headers.get("x-api-key") ?? bearer ?? "";
  const userId = VALID_KEYS[key];
  if (!userId) {
    return Promise.resolve(new Response(JSON.stringify({ status: 401, message: "invalid api key" }), { status: 401 }));
  }
  return Promise.resolve(
    new Response(JSON.stringify({ status: 200, data: { user_id: userId } }), { status: 200 }),
  );
}

function post(headers: Record<string, string> = {}, body: unknown = { hooks: ["first hook", "second hook"] }) {
  return new Request("http://localhost/api/v1/growth/rank-hooks", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

async function loadRoute() {
  vi.resetModules();
  return import("./route");
}

describe("POST /api/v1/growth/rank-hooks auth", () => {
  beforeEach(() => {
    meCalls = 0;
    apiDown = false;
    vi.stubEnv("TYPESAFE_API_KEY", "");
    vi.stubGlobal("fetch", vi.fn(fakeFetch));
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("returns 401 with no credential and never verifies or ranks", async () => {
    const { POST } = await loadRoute();
    const res = await POST(post());
    expect(res.status).toBe(401);
    expect(meCalls).toBe(0);
  });

  it("returns 401 for an unknown key", async () => {
    const { POST } = await loadRoute();
    const res = await POST(post({ "x-api-key": "stolen-or-made-up" }));
    expect(res.status).toBe(401);
    const body = (await res.json()) as { error: string };
    expect(body.error).not.toMatch(/TYPESAFE|x-api-key/);
  });

  it("returns 401 before parsing a bad body when unauthenticated", async () => {
    const { POST } = await loadRoute();
    const res = await POST(post({}, "not json at all"));
    expect(res.status).toBe(401);
  });

  it("ranks for a verified device key (x-api-key) and a Bearer token", async () => {
    const { POST } = await loadRoute();
    const res = await POST(post({ "x-api-key": "alice-key" }));
    expect(res.status).toBe(200);
    const body = (await res.json()) as { engine: string; variants: unknown[] };
    expect(body.engine).toBe("heuristic");
    expect(body.variants).toHaveLength(2);

    const bearer = await POST(post({ Authorization: "Bearer bob-key" }));
    expect(bearer.status).toBe(200);
  });

  it("caches a verified credential so a burst costs one /me call", async () => {
    const { POST } = await loadRoute();
    for (let i = 0; i < 3; i += 1) {
      expect((await POST(post({ "x-api-key": "alice-key" }))).status).toBe(200);
    }
    expect(meCalls).toBe(1);
  });

  it("returns 503 (not 401) when the API can't verify the session", async () => {
    apiDown = true;
    const { POST } = await loadRoute();
    const res = await POST(post({ "x-api-key": "alice-key" }));
    expect(res.status).toBe(503);
  });

  it("rate-limits per user with 429 + Retry-After, independent across users", async () => {
    const { POST } = await loadRoute();
    const alice = { "x-api-key": "alice-key" };
    for (let i = 0; i < 60; i += 1) {
      expect((await POST(post(alice))).status).toBe(200);
    }
    const limited = await POST(post(alice));
    expect(limited.status).toBe(429);
    expect(Number(limited.headers.get("Retry-After"))).toBeGreaterThan(0);

    const bob = await POST(post({ "x-api-key": "bob-key" }));
    expect(bob.status).toBe(200);
  });
});
