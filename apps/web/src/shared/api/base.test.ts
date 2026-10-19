import { describe, expect, it } from "vitest";
import { resolveApiBase } from "./base";

describe("resolveApiBase", () => {
  it("uses the configured NEXT_PUBLIC_API_BASE when present, trimming a trailing slash", () => {
    expect(resolveApiBase("https://api.menivor.com/api/v1/", "production")).toBe(
      "https://api.menivor.com/api/v1",
    );
  });

  it("uses the configured value in development too", () => {
    expect(resolveApiBase("https://staging.menivor.com/api/v1", "development")).toBe(
      "https://staging.menivor.com/api/v1",
    );
  });

  it("falls back to localhost:8080 outside production when unset", () => {
    expect(resolveApiBase(undefined, "development")).toBe("http://localhost:8080/api/v1");
    expect(resolveApiBase("", "test")).toBe("http://localhost:8080/api/v1");
  });

  it("never falls back to localhost in a production build missing the env var (menivor checkout outage, 2026-10-16: a production build without NEXT_PUBLIC_API_BASE baked localhost:8080 into the bundle, so every billing/catalog/payments-mode fetch from a real browser failed and /pricing CTAs stayed disabled with no error surfaced)", () => {
    expect(resolveApiBase(undefined, "production")).toBe("https://api.menivor.com/api/v1");
    expect(resolveApiBase("   ", "production")).toBe("https://api.menivor.com/api/v1");
  });
});
