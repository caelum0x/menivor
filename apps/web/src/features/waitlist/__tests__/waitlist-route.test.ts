import { beforeEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/waitlist/route";
import {
  MAX_WAITLIST_BODY_BYTES,
  WAITLIST_FALLBACK_EMAIL,
  validateWaitlistPayload,
} from "@/lib/waitlist";

const mocks = vi.hoisted(() => ({
  getCloudflareContext: vi.fn(),
  kvPut: vi.fn(async () => undefined),
}));

vi.mock("@opennextjs/cloudflare", () => ({
  getCloudflareContext: mocks.getCloudflareContext,
}));

function bindKv(): void {
  mocks.getCloudflareContext.mockReturnValue({
    env: { WAITLIST: { put: mocks.kvPut } },
  });
}

function post(body: string): Promise<Response> {
  return POST(
    new Request("http://localhost/api/waitlist", { method: "POST", body }),
  );
}

beforeEach(() => {
  mocks.getCloudflareContext.mockReset();
  mocks.kvPut.mockReset();
  mocks.kvPut.mockResolvedValue(undefined);
  vi.spyOn(console, "info").mockImplementation(() => undefined);
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

describe("waitlist payload validation", () => {
  it("normalizes email casing and whitespace", () => {
    const result = validateWaitlistPayload({ email: "  Creator@Example.COM " });
    expect(result).toMatchObject({
      ok: true,
      entry: { email: "creator@example.com", source: "" },
      honeypotTripped: false,
    });
  });

  it("rejects non-object bodies, missing and malformed emails", () => {
    expect(validateWaitlistPayload(null).ok).toBe(false);
    expect(validateWaitlistPayload(["a@b.co"]).ok).toBe(false);
    expect(validateWaitlistPayload({}).ok).toBe(false);
    expect(validateWaitlistPayload({ email: "   " }).ok).toBe(false);
    expect(validateWaitlistPayload({ email: "not-an-email" }).ok).toBe(false);
    expect(validateWaitlistPayload({ email: "a@b" }).ok).toBe(false);
    expect(
      validateWaitlistPayload({ email: `${"a".repeat(250)}@example.com` }).ok,
    ).toBe(false);
  });

  it("sanitizes the source tag down to a short slug", () => {
    const result = validateWaitlistPayload({
      email: "a@b.co",
      source: "  hero <script>alert(1)</script>  ",
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.entry.source).not.toMatch(/[<>() ]/);
      expect(result.entry.source.length).toBeLessThanOrEqual(64);
    }
  });

  it("flags a filled honeypot without validating it as an error", () => {
    const result = validateWaitlistPayload({
      email: "a@b.co",
      company: "Bot LLC",
    });
    expect(result).toMatchObject({ ok: true, honeypotTripped: true });
  });
});

describe("POST /api/waitlist", () => {
  it("stores a valid signup in KV keyed by normalized email", async () => {
    bindKv();
    const response = await post(
      JSON.stringify({ email: "Creator@Example.com", source: "hero" }),
    );
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ ok: true });
    expect(mocks.kvPut).toHaveBeenCalledTimes(1);
    const [key, value] = mocks.kvPut.mock.calls[0] as unknown as [string, string];
    expect(key).toBe("waitlist:creator@example.com");
    expect(JSON.parse(value)).toMatchObject({
      email: "creator@example.com",
      source: "hero",
    });
  });

  it("rejects malformed JSON and invalid emails with 400", async () => {
    bindKv();
    expect((await post("not json")).status).toBe(400);
    expect((await post(JSON.stringify({ email: "nope" }))).status).toBe(400);
    expect(mocks.kvPut).not.toHaveBeenCalled();
  });

  it("rejects oversized bodies with 413 before parsing", async () => {
    bindKv();
    const oversized = JSON.stringify({
      email: "a@b.co",
      source: "x".repeat(MAX_WAITLIST_BODY_BYTES),
    });
    expect((await post(oversized)).status).toBe(413);
    expect(mocks.kvPut).not.toHaveBeenCalled();
  });

  it("pretends success for honeypot submissions without storing", async () => {
    bindKv();
    const response = await post(
      JSON.stringify({ email: "bot@spam.co", company: "Bot LLC" }),
    );
    expect(response.status).toBe(200);
    expect(mocks.kvPut).not.toHaveBeenCalled();
  });

  it("returns 503 with the mailto fallback when no KV binding exists", async () => {
    // Local `next dev` / preview: getCloudflareContext throws outside Workers.
    mocks.getCloudflareContext.mockImplementation(() => {
      throw new Error("not in a Cloudflare context");
    });
    const response = await post(JSON.stringify({ email: "a@b.co" }));
    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toMatchObject({
      ok: false,
      fallbackEmail: WAITLIST_FALLBACK_EMAIL,
    });
  });

  it("returns 503 when the binding is declared but the write fails", async () => {
    bindKv();
    mocks.kvPut.mockRejectedValueOnce(new Error("kv down"));
    const response = await post(JSON.stringify({ email: "a@b.co" }));
    expect(response.status).toBe(503);
  });
});
