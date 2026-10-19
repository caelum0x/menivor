import { describe, expect, it } from "vitest";
import { ottSurfaceLive, P3_SURFACE_FLAGS } from "./flags";

describe("Wave P P3 OTT surface flags (PM3.0)", () => {
  it("are all off by default", () => {
    for (const surface of Object.keys(P3_SURFACE_FLAGS) as (keyof typeof P3_SURFACE_FLAGS)[]) {
      expect(ottSurfaceLive(surface)).toBe(false);
    }
  });

  it("need the master flag and their own flag", () => {
    expect(ottSurfaceLive("viewers", "1", undefined)).toBe(false);
    expect(ottSurfaceLive("viewers", undefined, "1")).toBe(false);
    expect(ottSurfaceLive("viewers", "true", "on")).toBe(true);
  });
});
