/**
 * Unit tests for the pure Clipfarm console helpers (`logic.ts`). No network —
 * these are the deterministic text → request-body / summary transforms the
 * Screen relies on.
 */

import { describe, expect, it } from "vitest";
import {
  buildRunInput,
  canTriggerRun,
  formatRunSummary,
  formatScheduleSummary,
  newIdempotencyKey,
  parseCsvList,
  parseSourceLines,
  runOutcome,
  totalRenderedToday,
} from "../logic";
import type { ChannelRunView } from "@/lib/series";

describe("parseSourceLines", () => {
  it("maps bare lines to a body and splits 'title | body'", () => {
    const out = parseSourceLines(
      "just a body\n  Headline | the story body \n\n  \nonly title | ",
    );
    expect(out).toEqual([
      { body: "just a body" },
      { title: "Headline", body: "the story body" },
    ]);
  });

  it("returns [] for blank input", () => {
    expect(parseSourceLines("")).toEqual([]);
    expect(parseSourceLines("   \n  ")).toEqual([]);
  });
});

describe("parseCsvList", () => {
  it("splits on commas/newlines, trims, dedupes and drops blanks", () => {
    expect(parseCsvList("a, b\n c ,a,, b ")).toEqual(["a", "b", "c"]);
  });
});

describe("buildRunInput", () => {
  it("omits empty collections so backend defaults apply", () => {
    const input = buildRunInput({ sourceText: "one\ntwo" });
    expect(input.source_items).toHaveLength(2);
    expect(input.hooks).toBeUndefined();
    expect(input.accounts).toBeUndefined();
    expect(input.platforms).toBeUndefined();
    expect(input.subject).toBeUndefined();
  });

  it("includes overrides that were set", () => {
    const input = buildRunInput({
      sourceText: "one",
      hooksText: "hookA, hookB",
      accountsText: "acct1",
      platforms: ["tiktok"],
      subject: " space facts ",
      maxPerAccount: 5,
    });
    expect(input.hooks).toEqual(["hookA", "hookB"]);
    expect(input.accounts).toEqual(["acct1"]);
    expect(input.platforms).toEqual(["tiktok"]);
    expect(input.subject).toBe("space facts");
    expect(input.max_per_account).toBe(5);
  });
});

describe("canTriggerRun", () => {
  it("requires at least one source item", () => {
    expect(canTriggerRun(buildRunInput({ sourceText: "" }))).toBe(false);
    expect(canTriggerRun(buildRunInput({ sourceText: "hi" }))).toBe(true);
  });
});

describe("totalRenderedToday", () => {
  it("sums per-account counts, ignoring non-finite values", () => {
    expect(totalRenderedToday({ a: 2, b: 3 })).toBe(5);
    expect(totalRenderedToday({})).toBe(0);
  });
});

describe("summary formatters", () => {
  it("formats a run summary", () => {
    expect(
      formatRunSummary({
        planned: 4,
        skipped_duplicates: 1,
        paced_out: 1,
        rendered: 2,
        enqueue_failures: 0,
      }),
    ).toBe("2 rendered · 1 paced out · 1 dupes · 0 failed");
  });

  it("formats a schedule summary", () => {
    expect(formatScheduleSummary({ considered: 3, scheduled: 2 })).toBe(
      "2 scheduled of 3 considered",
    );
  });
});

describe("runOutcome", () => {
  it("extracts a stored summary or returns null", () => {
    const run: ChannelRunView = {
      id: "r1",
      channel_id: "c1",
      user_id: "u1",
      params: {
        summary: {
          planned: 1,
          skipped_duplicates: 0,
          paced_out: 0,
          rendered: 1,
          enqueue_failures: 0,
        },
      },
      created_at: null,
    };
    expect(runOutcome(run)?.rendered).toBe(1);

    const bare: ChannelRunView = {
      id: "r2",
      channel_id: "c1",
      user_id: "u1",
      params: {},
      created_at: null,
    };
    expect(runOutcome(bare)).toBe(null);
  });
});

describe("newIdempotencyKey", () => {
  it("mints a unique, scope-prefixed key", () => {
    const a = newIdempotencyKey("run");
    const b = newIdempotencyKey("run");
    expect(a).not.toBe(b);
    expect(a.startsWith("clipfarm-run-")).toBe(true);
    expect(newIdempotencyKey("schedule").startsWith("clipfarm-schedule-")).toBe(
      true,
    );
  });
});
