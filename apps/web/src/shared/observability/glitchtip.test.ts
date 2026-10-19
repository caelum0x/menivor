import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MAX_EVENTS_PER_PAGE,
  buildEvent,
  initGlitchTip,
  parseDsn,
  resetGlitchTipForTests,
  scrubText,
  scrubUrl,
  toErrorInput,
} from "./glitchtip";

const DSN = "https://abc123@errors.example.com/7";

afterEach(() => {
  resetGlitchTipForTests();
  vi.unstubAllGlobals();
});

describe("parseDsn", () => {
  it("builds the store endpoint", () => {
    expect(parseDsn(DSN)?.storeUrl).toBe(
      "https://errors.example.com/api/7/store/?sentry_key=abc123&sentry_version=7",
    );
  });

  it("rejects missing or malformed DSNs", () => {
    expect(parseDsn(undefined)).toBeNull();
    expect(parseDsn("")).toBeNull();
    expect(parseDsn("not a url")).toBeNull();
    expect(parseDsn("https://errors.example.com/7")).toBeNull();
    expect(parseDsn("https://k@errors.example.com/abc")).toBeNull();
  });
});

describe("scrubbing", () => {
  it("drops query strings and fragments", () => {
    expect(scrubUrl("https://menivor.com/billing?checkout_id=ch_1#x")).toBe("https://menivor.com/billing");
    expect(scrubUrl("https://menivor.com/reels")).toBe("https://menivor.com/reels");
    expect(scrubText("at f (https://menivor.com/_next/a.js?token=abc:1:2)")).toBe(
      "at f (https://menivor.com/_next/a.js)",
    );
  });

  it("builds an event without any user data", () => {
    const event = buildEvent(
      { name: "TypeError", message: "x is undefined", stack: "TypeError\n at y" },
      { url: "https://menivor.com/create?email=a@b.c" },
    );
    expect(event.user).toBeUndefined();
    expect(event.request).toEqual({ url: "https://menivor.com/create" });
    expect(JSON.stringify(event)).not.toContain("a@b.c");
  });

  it("normalizes non-errors", () => {
    expect(toErrorInput("boom")).toEqual({ name: "Error", message: "boom" });
    expect(toErrorInput({ any: 1 }).message).toBe("Non-error rejection");
  });
});

describe("initGlitchTip", () => {
  it("is off without a DSN", () => {
    expect(initGlitchTip(undefined)).toBe(false);
  });

  it("reports once per distinct error and caps per page", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    expect(initGlitchTip(DSN)).toBe(true);
    expect(initGlitchTip(DSN)).toBe(false);
    const fire = (message: string) =>
      window.dispatchEvent(new ErrorEvent("error", { error: new Error(message), message }));
    fire("same");
    fire("same");
    for (let i = 0; i < MAX_EVENTS_PER_PAGE + 3; i += 1) fire(`distinct ${i}`);
    expect(fetchMock).toHaveBeenCalledTimes(MAX_EVENTS_PER_PAGE);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/7/store/");
    expect(init.credentials).toBe("omit");
  });
});
