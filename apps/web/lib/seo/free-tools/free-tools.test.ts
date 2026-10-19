import { describe, expect, it } from "vitest";
import {
  chunksToCues,
  chunksToTranscript,
  convertSubtitles,
  detectFormat,
  formatTimestamp,
  parseSubtitles,
  parseTimestamp,
  scaleCues,
  serializeSubtitles,
  shiftCues,
  splitText,
} from "./subtitles";
import {
  bitsPerPixel,
  fileSizeMB,
  fitFrame,
  parseDuration,
  parseRatio,
  simplifyRatio,
  solveDimension,
  videoBitrateForSize,
} from "./video-math";
import { buildPrompt, parseOutput, validateGenerateRequest } from "./generate";
import { FREE_TOOLS, FREE_TOOL_SLUGS, getFreeTool } from "./catalog";
import { USE_CASE_SLUGS } from "../usecases";

const SRT = `1
00:00:01,000 --> 00:00:03,500
Hello there

2
00:00:04,250 --> 00:00:06,000
Second line
two rows
`;

describe("subtitles", () => {
  it("parses and formats timestamps", () => {
    expect(parseTimestamp("01:02:03,456")).toBe(3_723_456);
    expect(parseTimestamp("02:03.4")).toBe(123_400);
    expect(parseTimestamp("nope")).toBeNull();
    expect(formatTimestamp(3_723_456, "srt")).toBe("01:02:03,456");
    expect(formatTimestamp(3_723_456, "vtt")).toBe("01:02:03.456");
    expect(formatTimestamp(-50, "vtt")).toBe("00:00:00.000");
  });

  it("parses SRT cues including multi-line text and CRLF", () => {
    const cues = parseSubtitles(SRT.replace(/\n/g, "\r\n"));
    expect(cues).toEqual([
      { startMs: 1000, endMs: 3500, text: "Hello there" },
      { startMs: 4250, endMs: 6000, text: "Second line\ntwo rows" },
    ]);
  });

  it("converts SRT to VTT and back losslessly", () => {
    const vtt = convertSubtitles(SRT, "vtt");
    expect(vtt.startsWith("WEBVTT\n\n00:00:01.000 --> 00:00:03.500\nHello there")).toBe(true);
    expect(detectFormat(vtt)).toBe("vtt");
    expect(detectFormat(SRT)).toBe("srt");
    expect(convertSubtitles(vtt, "srt")).toBe(SRT);
  });

  it("ignores VTT headers, NOTE blocks, identifiers and cue settings", () => {
    const vtt = "WEBVTT - title\n\nNOTE hello\n\nintro\n00:01.000 --> 00:02.000 align:start line:0\nHi\n";
    expect(parseSubtitles(vtt)).toEqual([{ startMs: 1000, endMs: 2000, text: "Hi" }]);
  });

  it("shifts cues and drops cues that end before zero", () => {
    const cues = parseSubtitles(SRT);
    expect(shiftCues(cues, 1500)[0]).toEqual({ startMs: 2500, endMs: 5000, text: "Hello there" });
    const earlier = shiftCues(cues, -4000);
    expect(earlier).toHaveLength(1);
    expect(earlier[0]).toMatchObject({ startMs: 250, endMs: 2000 });
    expect(shiftCues(cues, -1200)[0]).toMatchObject({ startMs: 0, endMs: 2300 });
  });

  it("scales cues for frame-rate drift", () => {
    const cues = parseSubtitles(SRT);
    expect(scaleCues(cues, 25 / 23.976)[0]?.startMs).toBe(1043);
    expect(scaleCues(cues, 0)).toEqual(cues);
  });

  it("serializes empty input safely", () => {
    expect(serializeSubtitles([], "srt")).toBe("");
    expect(serializeSubtitles([], "vtt")).toBe("WEBVTT\n\n");
  });

  it("splits text and builds caption cues from speech chunks", () => {
    expect(splitText("one two three four", 9)).toEqual(["one two", "three", "four"]);
    const cues = chunksToCues(
      [
        { text: " This is a long sentence that needs two caption lines here", start: 0, end: 4 },
        { text: "Short", start: 4, end: null },
        { text: "   ", start: 5, end: 6 },
      ],
      30,
    );
    expect(cues).toHaveLength(3);
    expect(cues[0]?.startMs).toBe(0);
    expect(cues[1]?.endMs).toBe(4000);
    expect(cues[2]).toEqual({ startMs: 4000, endMs: 5000, text: "Short" });
    expect(chunksToTranscript([{ text: "Hi there.", start: 0, end: 1 }, { text: "Next one", start: 1, end: 2 }])).toBe(
      "Hi there.\nNext one",
    );
  });
});

describe("video math", () => {
  it("simplifies and parses ratios", () => {
    expect(simplifyRatio(1080, 1920)).toBe("9:16");
    expect(simplifyRatio(1080, 1350)).toBe("4:5");
    expect(simplifyRatio(0, 10)).toBe("");
    expect(parseRatio("9:16")).toEqual([9, 16]);
    expect(parseRatio("1.91x1")).toEqual([1.91, 1]);
    expect(parseRatio("abc")).toBeNull();
  });

  it("solves the missing dimension with even pixels", () => {
    expect(solveDimension([9, 16], { width: 1080 })).toEqual({ width: 1080, height: 1920 });
    expect(solveDimension([9, 16], { height: 1000 })).toEqual({ width: 562, height: 1000 });
    expect(solveDimension([9, 16], {})).toBeNull();
  });

  it("fits landscape footage into a vertical frame", () => {
    const target = { width: 1080, height: 1920 };
    expect(fitFrame({ width: 1920, height: 1080 }, target, "pad")).toMatchObject({ width: 1080, height: 608, padY: 1312 });
    expect(fitFrame({ width: 1920, height: 1080 }, target, "crop")).toMatchObject({ width: 3414, height: 1920 });
  });

  it("converts between bitrate and file size", () => {
    expect(fileSizeMB(8000, 128, 60)).toBeCloseTo(60.96, 2);
    expect(videoBitrateForSize(50, 60, 128)).toBe(6405);
    expect(videoBitrateForSize(1, 0, 128)).toBe(0);
    expect(videoBitrateForSize(0.01, 600, 128)).toBe(0);
    expect(bitsPerPixel(8000, 1080, 1920, 30)).toBeCloseTo(0.1286, 3);
  });

  it("parses durations", () => {
    expect(parseDuration("90")).toBe(90);
    expect(parseDuration("1:30")).toBe(90);
    expect(parseDuration("01:02:03")).toBe(3723);
    expect(parseDuration("1:x")).toBeNull();
  });
});

describe("generator", () => {
  it("validates requests", () => {
    expect(validateGenerateRequest(null).ok).toBe(false);
    expect(validateGenerateRequest({ kind: "bad", topic: "coffee shop" }).ok).toBe(false);
    expect(validateGenerateRequest({ kind: "hooks", topic: "a" }).ok).toBe(false);
    expect(validateGenerateRequest({ kind: "hooks", topic: "x".repeat(301) }).ok).toBe(false);
    const ok = validateGenerateRequest({ kind: "script", topic: "  cold   brew ", platform: "zzz", lengthSec: 60 });
    expect(ok).toEqual({
      ok: true,
      value: { kind: "script", topic: "cold brew", platform: "tiktok", tone: "bold", lengthSec: 60 },
    });
  });

  it("fences the topic in the prompt", () => {
    const res = validateGenerateRequest({ kind: "titles", topic: "budget travel in Japan", platform: "youtube" });
    if (!res.ok) throw new Error("expected ok");
    const prompt = buildPrompt(res.value);
    expect(prompt).toContain("<topic>budget travel in Japan</topic>");
    expect(prompt).toContain("60 characters");
  });

  it("parses list output, strips emoji and dedupes", () => {
    const out = parseOutput("hooks", '```json\n{"items":["Stop doing this 🚫","Stop doing this","\\"Quoted\\""]}\n```');
    expect(out).toEqual({ kind: "list", items: ["Stop doing this", "Quoted"] });
    expect(parseOutput("hashtags", '{"items":["#Cold Brew","coffee!","#"]}')).toEqual({
      kind: "list",
      items: ["#coldbrew", "#coffee"],
    });
    expect(parseOutput("titles", "no json")).toBeNull();
  });

  it("parses script output", () => {
    const out = parseOutput("script", '{"hook":"Hi","beats":[{"say":"One","show":"cup"},{"say":""}],"cta":"Follow"}');
    expect(out).toEqual({ kind: "script", script: { hook: "Hi", beats: [{ say: "One", show: "cup" }], cta: "Follow" } });
    expect(parseOutput("script", '{"hook":"Hi","beats":[]}')).toBeNull();
  });
});

describe("free tool catalog", () => {
  it("has unique slugs that do not collide with use-case pages", () => {
    expect(new Set(FREE_TOOL_SLUGS).size).toBe(FREE_TOOLS.length);
    for (const slug of FREE_TOOL_SLUGS) expect(USE_CASE_SLUGS).not.toContain(slug);
  });

  it("gives every tool unique metadata, steps, FAQs and valid related links", () => {
    const titles = new Set(FREE_TOOLS.map((tool) => tool.title));
    expect(titles.size).toBe(FREE_TOOLS.length);
    for (const tool of FREE_TOOLS) {
      expect(tool.description.length).toBeGreaterThan(70);
      expect(tool.description.length).toBeLessThanOrEqual(160);
      expect(tool.title.length).toBeLessThanOrEqual(60);
      expect(tool.steps.length).toBeGreaterThanOrEqual(3);
      expect(tool.faqs.length).toBeGreaterThanOrEqual(3);
      expect(tool.body.length).toBeGreaterThanOrEqual(2);
      for (const slug of tool.related) expect(getFreeTool(slug)).toBeDefined();
    }
  });
});

describe("offline templates", () => {
  it("extracts a core phrase and keywords", async () => {
    const { corePhrase, keywords } = await import("./templates");
    expect(corePhrase("A cold brew coffee kit for busy parents who want cafe coffee")).toBe("cold brew coffee kit");
    expect(corePhrase("SEO tips, explained")).toBe("SEO tips");
    expect(keywords("How to make the best cold brew at home")).toEqual(["make", "best", "cold", "brew", "home"]);
  });

  it("returns ten distinct hooks and titles and shuffles by seed", async () => {
    const { templateHooks, templateTitles } = await import("./templates");
    const hooks = templateHooks("cold brew coffee", 1);
    expect(hooks).toHaveLength(10);
    expect(new Set(hooks).size).toBe(10);
    expect(hooks.every((hook) => hook.toLowerCase().includes("cold brew coffee"))).toBe(true);
    const titles = templateTitles("cold brew coffee", 2);
    expect(titles).toHaveLength(10);
    expect(titles.every((title) => title.length <= 70)).toBe(true);
    expect(templateTitles("cold brew coffee", 3)).not.toEqual(titles);
  });

  it("builds hashtags and a script for any request", async () => {
    const { templateOutput, templateHashtags } = await import("./templates");
    const tags = templateHashtags("Easy high protein breakfast ideas", "tiktok");
    expect(tags.slice(0, 2)).toEqual(["#highprotein", "#proteinbreakfast"]);
    expect(tags).toContain("#breakfast");
    expect(tags).toContain("#tiktoktips");
    expect(tags.every((tag) => /^#[\p{L}\p{N}]+$/u.test(tag))).toBe(true);
    const script = templateOutput({ kind: "script", topic: "cold brew", platform: "tiktok", tone: "bold", lengthSec: 15 });
    expect(script.kind === "script" && script.script.beats.length).toBe(2);
    const sixty = templateOutput({ kind: "script", topic: "cold brew", platform: "tiktok", tone: "bold", lengthSec: 60 });
    expect(sixty.kind === "script" && sixty.script.beats.length).toBe(5);
  });
});
