import { describe, expect, it, vi } from "vitest";

import {
  interpretWaitlistResponse,
  submitWaitlist,
  validateEmail,
  type FetchLike,
} from "../waitlist";

describe("validateEmail", () => {
  it("accepts and normalizes a plausible address", () => {
    const result = validateEmail("  Creator@Menivor.COM ");
    expect(result).toEqual({ ok: true, email: "creator@menivor.com" });
  });

  it("rejects an empty string with a friendly message", () => {
    const result = validateEmail("   ");
    expect(result).toEqual({
      ok: false,
      error: "Please enter your email address.",
    });
  });

  it.each([
    "not-an-email",
    "missing@tld",
    "@nolocal.com",
    "spaces in@email.com",
    "trailing@dot.",
  ])("rejects malformed address %s", (bad) => {
    const result = validateEmail(bad);
    expect(result.ok).toBe(false);
  });

  it("rejects an over-length address", () => {
    const huge = `${"a".repeat(250)}@x.com`;
    expect(validateEmail(huge).ok).toBe(false);
  });
});

function jsonResponse(
  ok: boolean,
  status: number,
  body: unknown,
): { ok: boolean; status: number; json: () => Promise<unknown> } {
  return { ok, status, json: () => Promise.resolve(body) };
}

describe("interpretWaitlistResponse", () => {
  it("maps a 2xx to ok", async () => {
    expect(await interpretWaitlistResponse(jsonResponse(true, 200, { ok: true }))).toEqual(
      { status: "ok" },
    );
  });

  it("maps a 503 to unavailable", async () => {
    expect(
      await interpretWaitlistResponse(jsonResponse(false, 503, { ok: false })),
    ).toEqual({ status: "unavailable" });
  });

  it("maps a 400 with a message to error", async () => {
    expect(
      await interpretWaitlistResponse(
        jsonResponse(false, 400, { error: "Please enter a valid email address." }),
      ),
    ).toEqual({ status: "error", message: "Please enter a valid email address." });
  });
});

describe("submitWaitlist", () => {
  it("short-circuits on an invalid email without calling fetch", async () => {
    const fetchImpl = vi.fn();
    const result = await submitWaitlist("nope", "mobile-test", {
      fetch: fetchImpl as unknown as FetchLike,
    });
    expect(result.status).toBe("invalid");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("posts the web payload shape and returns ok on success", async () => {
    const fetchImpl: FetchLike = vi.fn(async (_url, init) => {
      const body = JSON.parse(init.body) as Record<string, unknown>;
      expect(body).toEqual({
        email: "creator@menivor.com",
        source: "mobile-waitlist",
        company: "",
      });
      return jsonResponse(true, 200, { ok: true });
    });
    const result = await submitWaitlist("Creator@Menivor.com", "mobile-waitlist", {
      fetch: fetchImpl,
    });
    expect(result).toEqual({ status: "ok" });
  });

  it("degrades a thrown network error to unavailable", async () => {
    const fetchImpl: FetchLike = vi.fn(async () => {
      throw new Error("network down");
    });
    const result = await submitWaitlist("creator@menivor.com", "src", {
      fetch: fetchImpl,
    });
    expect(result).toEqual({ status: "unavailable" });
  });

  it("forwards a honeypot value when provided", async () => {
    const fetchImpl: FetchLike = vi.fn(async (_url, init) => {
      const body = JSON.parse(init.body) as Record<string, unknown>;
      expect(body.company).toBe("bot");
      return jsonResponse(true, 200, { ok: true });
    });
    await submitWaitlist("creator@menivor.com", "src", {
      fetch: fetchImpl,
      honeypot: "bot",
    });
    expect(fetchImpl).toHaveBeenCalledOnce();
  });
});
