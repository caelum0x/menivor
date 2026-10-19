import { describe, expect, it } from "vitest";

import { parseRunMeta, runKey } from "../run-store";

describe("run-store serialisation", () => {
  it("keys a run independently of job order", () => {
    expect(runKey(["job_c3", "job_a1", "job_b2"])).toBe("job_a1,job_b2,job_c3");
  });

  it("round-trips a stored run and drops unknown hook angles", () => {
    const raw = JSON.stringify({
      source: "link",
      input: "https://shop.com/p/1",
      presetId: "product",
      startedAt: 1700000000000,
      batchId: "abcdef123456",
      notice: "2 of 3 variants started.",
      variants: [
        { jobId: "job_a1", angle: "pov", hook: "POV: you just found it." },
        { jobId: "job_b2", angle: "bogus" },
        { angle: "pov" },
      ],
    });
    expect(parseRunMeta(raw)).toEqual({
      source: "link",
      input: "https://shop.com/p/1",
      presetId: "product",
      startedAt: 1700000000000,
      batchId: "abcdef123456",
      notice: "2 of 3 variants started.",
      variants: [
        { jobId: "job_a1", angle: "pov", hook: "POV: you just found it." },
        { jobId: "job_b2" },
      ],
    });
  });

  it("rejects malformed or foreign payloads", () => {
    expect(parseRunMeta(null)).toBeNull();
    expect(parseRunMeta("not json")).toBeNull();
    expect(parseRunMeta(JSON.stringify({ source: "video", input: "", startedAt: 1, variants: [] }))).toBeNull();
    expect(parseRunMeta(JSON.stringify({ source: "topic", input: "x", startedAt: "1", variants: [] }))).toBeNull();
    const badBatch = parseRunMeta(
      JSON.stringify({ source: "topic", input: "x", startedAt: 1, variants: [], batchId: "../x" }),
    );
    expect(badBatch?.batchId).toBeUndefined();
  });
});
