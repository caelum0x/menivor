import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/newsletter/route";
import { readListmonkConfig, subscribeToListmonk } from "@/lib/listmonk";

const LIST_UUID = "0b9d2c1e-7a3f-4c5d-9e8f-1a2b3c4d5e6f";

function post(body: unknown): Promise<Response> {
  return POST(
    new Request("http://localhost/api/newsletter", {
      method: "POST",
      body: typeof body === "string" ? body : JSON.stringify(body),
    }),
  );
}

function listmonkReply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  vi.stubEnv("LISTMONK_URL", "https://news.example.test/");
  vi.stubEnv("LISTMONK_LIST_UUID", LIST_UUID);
  vi.spyOn(console, "info").mockImplementation(() => undefined);
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("readListmonkConfig", () => {
  it("returns null when unset or malformed", () => {
    expect(readListmonkConfig({})).toBeNull();
    expect(readListmonkConfig({ LISTMONK_URL: "https://x.test", LISTMONK_LIST_UUID: "nope" })).toBeNull();
    expect(readListmonkConfig({ LISTMONK_URL: "x.test", LISTMONK_LIST_UUID: LIST_UUID })).toBeNull();
  });

  it("trims the trailing slash and splits list UUIDs", () => {
    expect(
      readListmonkConfig({ LISTMONK_URL: "https://x.test//", LISTMONK_LIST_UUID: `${LIST_UUID}, ${LIST_UUID}` }),
    ).toEqual({ url: "https://x.test", listUuids: [LIST_UUID, LIST_UUID] });
  });
});

describe("subscribeToListmonk", () => {
  const config = { url: "https://x.test", listUuids: [LIST_UUID] };

  it("maps a network failure to unavailable without throwing", async () => {
    const failing = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    await expect(subscribeToListmonk(config, { email: "a@b.co" }, failing)).resolves.toMatchObject({
      ok: false,
      reason: "unavailable",
    });
  });

  it("maps 400 to rejected and 5xx to unavailable", async () => {
    const bad = vi.fn(async () => listmonkReply(400, { message: "invalid email" }));
    await expect(subscribeToListmonk(config, { email: "a@b.co" }, bad)).resolves.toEqual({
      ok: false,
      reason: "rejected",
      detail: "invalid email",
    });
    const down = vi.fn(async () => listmonkReply(502, {}));
    await expect(subscribeToListmonk(config, { email: "a@b.co" }, down)).resolves.toMatchObject({
      reason: "unavailable",
    });
  });
});

describe("POST /api/newsletter", () => {
  it("forwards a consented signup to the listmonk public API", async () => {
    fetchMock.mockResolvedValue(listmonkReply(200, { data: { has_optin: true } }));
    const response = await post({ email: "  Person@Example.COM ", consent: true });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true, needsConfirmation: true });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://news.example.test/api/public/subscription");
    expect(JSON.parse(String(init.body))).toEqual({
      email: "person@example.com",
      name: "",
      list_uuids: [LIST_UUID],
    });
    // Public endpoint: no admin credentials are ever sent.
    expect(JSON.stringify(init.headers)).not.toMatch(/authorization/i);
  });

  it("requires consent", async () => {
    const response = await post({ email: "a@b.co", consent: false });
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects an invalid email and non-JSON bodies", async () => {
    expect((await post({ email: "nope", consent: true })).status).toBe(400);
    expect((await post("not json")).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("silently drops honeypot submissions", async () => {
    const response = await post({ email: "a@b.co", consent: true, company: "Acme" });
    expect(response.status).toBe(200);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns a clear 503 when listmonk is not configured", async () => {
    vi.stubEnv("LISTMONK_URL", "");
    const response = await post({ email: "a@b.co", consent: true });
    expect(response.status).toBe(503);
    expect((await response.json()).error).toMatch(/not switched on/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns 503 when listmonk is down", async () => {
    fetchMock.mockResolvedValue(listmonkReply(500, {}));
    expect((await post({ email: "a@b.co", consent: true })).status).toBe(503);
  });
});

describe("POST /api/newsletter rate limit", () => {
  function postFrom(ip: string): Promise<Response> {
    return POST(
      new Request("http://localhost/api/newsletter", {
        method: "POST",
        headers: { "cf-connecting-ip": ip },
        body: JSON.stringify({ email: "a@b.co", consent: true }),
      }),
    );
  }

  it("allows 5 signups per hour per IP, then returns 429 with Retry-After", async () => {
    fetchMock.mockImplementation(async () => listmonkReply(200, { data: { has_optin: true } }));
    for (let attempt = 0; attempt < 5; attempt += 1) {
      expect((await postFrom("203.0.113.7")).status).toBe(200);
    }
    const limited = await postFrom("203.0.113.7");
    expect(limited.status).toBe(429);
    expect(Number(limited.headers.get("Retry-After"))).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalledTimes(5);

    // A different client is unaffected.
    expect((await postFrom("198.51.100.4")).status).toBe(200);
  });
});

describe("createRateLimiter", () => {
  it("refills over the window", async () => {
    const { createRateLimiter } = await import("@/lib/rate-limit");
    const limiter = createRateLimiter({ capacity: 2, refillMs: 1000 });
    expect(limiter.check("k", 0).allowed).toBe(true);
    expect(limiter.check("k", 0).allowed).toBe(true);
    expect(limiter.check("k", 0)).toEqual({ allowed: false, retryAfterSeconds: 1 });
    expect(limiter.check("k", 500).allowed).toBe(true);
  });
});
