/**
 * Port of apps/web/src/features/create-compose/one-flow/plan.test.ts plus the
 * mobile-only helpers (catalog defaults, error copy, run cost). Both suites
 * must pass so the phone and the web send identical run requests.
 */
import { describe, expect, it } from "vitest";
import { JobState } from "@/lib/types";
import {
  CREDITS_PER_REEL,
  VARIANT_COUNT,
  bareVoiceId,
  HOOK_ANGLES,
  buildJobRequest,
  buildLinkBody,
  buildRunRegistration,
  defaultVoiceFor,
  describeCreateError,
  describeRunCost,
  hookStyleLabel,
  hostOf,
  isHookStyle,
  missingCatalogParts,
  runCost,
  topicRunVariants,
  currentStageLabel,
  defaultPresetFor,
  findPreset,
  formatElapsed,
  parseJobIds,
  parseSource,
  pickBackground,
  planLinkVariants,
  resolvePreset,
  resultsHref,
  variantPhase,
  variantProgress,
  voiceIdOf,
} from "../plan";

describe("parseSource", () => {
  it("returns null for empty input", () => {
    expect(parseSource("   ")).toBeNull();
    expect(parseSource(undefined)).toBeNull();
  });

  it("treats an http(s) URL as a link", () => {
    expect(parseSource(" https://shop.com/products/mug ")).toEqual({
      kind: "link",
      value: "https://shop.com/products/mug",
    });
  });

  it("upgrades a bare domain to an https link", () => {
    expect(parseSource("shop.example.com/p/1")).toEqual({
      kind: "link",
      value: "https://shop.example.com/p/1",
    });
  });

  it("treats text with spaces as a topic", () => {
    expect(parseSource("why people quit the gym")).toEqual({
      kind: "topic",
      value: "why people quit the gym",
    });
  });

  it("does not treat non-http schemes or single words as links", () => {
    expect(parseSource("javascript:alert(1)")?.kind).toBe("topic");
    expect(parseSource("productivity")?.kind).toBe("topic");
  });

  it("clamps very long topics", () => {
    const parsed = parseSource(`a ${"b".repeat(1000)}`);
    expect(parsed?.value.length).toBe(300);
  });
});

describe("presets", () => {
  it("defaults links to the product ad and topics to the presenter", () => {
    expect(defaultPresetFor("link")).toBe("product");
    expect(defaultPresetFor("topic")).toBe("talking");
  });

  it("maps presets to real pipeline layouts", () => {
    expect(findPreset("talking")?.layout).toBe("pip");
    expect(findPreset("product")?.layout).toBe("hook_intro");
    expect(findPreset("story")?.layout).toBe("split");
    expect(findPreset("nope")).toBeUndefined();
  });

  it("offers a faceless story that needs no presenter", () => {
    const faceless = findPreset("faceless");
    expect(faceless?.layout).toBe("captions_only");
    expect(faceless?.needsPresenter).toBe(false);
    expect(faceless?.preferredBackground).toBe("block-runner");
    expect(findPreset("talking")?.needsPresenter).toBe(true);
  });
});

describe("hook styles", () => {
  it("uses the API hook_style ids for the link angles", () => {
    expect(HOOK_ANGLES.map((a) => a.id)).toEqual(["pov", "question", "nobody_tells_you"]);
    expect(isHookStyle("stat")).toBe(true);
    expect(isHookStyle("secret")).toBe(false);
    expect(isHookStyle("toString")).toBe(false);
    expect(hookStyleLabel("story")).toBe("Story hook");
    expect(hookStyleLabel(undefined)).toBe("");
  });

  it("maps the API's per-variant hook styles onto a topic run", () => {
    expect(
      topicRunVariants({
        job_id: "job_a1",
        job_ids: ["job_a1", "job_b2", "job_c3"],
        hook_styles: ["pov", "question", "bogus"],
      }),
    ).toEqual([
      { jobId: "job_a1", angle: "pov" },
      { jobId: "job_b2", angle: "question" },
      { jobId: "job_c3" },
    ]);
    expect(topicRunVariants({ job_id: "solo01" })).toEqual([{ jobId: "solo01" }]);
  });

  it("registers a link run only when at least two variants started", () => {
    expect(buildRunRegistration([{ jobId: "job_a1", angle: "pov" }])).toBeNull();
    expect(
      buildRunRegistration([
        { jobId: "job_a1", angle: "pov" },
        { jobId: "job_b2", angle: "question" },
      ]),
    ).toEqual({
      variants: [
        { job_id: "job_a1", hook_style: "pov" },
        { job_id: "job_b2", hook_style: "question" },
      ],
    });
  });
});

describe("planLinkVariants", () => {
  const content = {
    title: "Ceramic Pour-Over Set",
    description: "A hand-glazed dripper and carafe for slow mornings",
    features: ["Holds 600 ml", "Dishwasher safe", "Fits standard #2 filters", "Extra"],
  };

  it("makes three scripts with the same body and different hooks", () => {
    const plans = planLinkVariants(content, "en");
    expect(plans).toHaveLength(VARIANT_COUNT);
    const hooks = plans.map((p) => p.hook);
    expect(new Set(hooks).size).toBe(VARIANT_COUNT);
    const bodies = plans.map((p) => p.script.split("\n\n").slice(1).join("\n\n"));
    expect(new Set(bodies).size).toBe(1);
    for (const plan of plans) {
      expect(plan.script.split("\n\n")[0]).toBe(plan.hook);
      expect(plan.hook).toContain("Ceramic Pour-Over Set");
    }
  });

  it("uses only page content plus a CTA in the body, capped at three features", () => {
    const body = buildLinkBody(content, "en");
    expect(body).toEqual([
      "A hand-glazed dripper and carafe for slow mornings.",
      "Holds 600 ml.",
      "Dishwasher safe.",
      "Fits standard #2 filters.",
      "Check the link to try it.",
    ]);
  });

  it("writes Turkish hooks and CTA for Turkish reels", () => {
    const plans = planLinkVariants(content, "tr");
    expect(plans[1]?.hook).toContain("değer mi");
    expect(plans[0]?.script.endsWith("Denemek için linke göz at.")).toBe(true);
  });

  it("still produces a script when the page had no description or features", () => {
    const plans = planLinkVariants({ title: "", description: "", features: [] }, "en");
    expect(plans[0]?.script).toContain("This is worth a look.");
    expect(plans[0]?.hook).toBe("POV: you just found this.");
  });
});

describe("buildJobRequest", () => {
  const base = {
    subject: "Morning routines",
    layout: "pip" as const,
    avatarId: "av_1",
    voiceId: "elevenlabs:v_9",
    backgroundId: "minecraft-parkour",
    language: "en" as const,
  };

  it("builds the wizard-shaped body with a background and no screen recording", () => {
    const body = buildJobRequest({ ...base, variants: 3 });
    expect(body.variants).toBe(3);
    expect(body.voice_id).toBe("v_9");
    expect(body.avatar_id).toBe("av_1");
    expect(body.params).toMatchObject({
      video_subject: "Morning routines",
      voice_name: "elevenlabs:v_9",
      avatar_id: "av_1",
      avatar_provider: "heygen",
      layout: "pip",
      aspect: "9:16",
      screen_recording_key: "",
      background_id: "minecraft-parkour",
    });
    expect(body.params.video_script).toBeUndefined();
  });

  it("includes a manual script and clamps variants to 1..3", () => {
    const body = buildJobRequest({ ...base, script: "Hook\n\nBody", variants: 9 });
    expect(body.params.video_script).toBe("Hook\n\nBody");
    expect(body.variants).toBe(3);
    expect(buildJobRequest({ ...base, variants: 0 }).variants).toBe(1);
  });

  it("sends the hook angle when one is chosen", () => {
    const body = buildJobRequest({ ...base, script: "POV: x\n\nBody", hookStyle: "pov" });
    expect(body.params).toMatchObject({ hook_style: "pov" });
    expect(buildJobRequest(base).params).not.toHaveProperty("hook_style");
  });

  it("sends no presenter for the faceless layout so the API narrates with TTS", () => {
    const body = buildJobRequest({ ...base, layout: "captions_only", variants: 3 });
    expect(body.avatar_id).toBeUndefined();
    expect(body.voice_id).toBe("v_9");
    expect(body.params).toMatchObject({
      layout: "captions_only",
      avatar_id: "",
      voice_name: "elevenlabs:v_9",
      screen_recording_key: "",
      background_id: "minecraft-parkour",
    });
    expect(body.params).not.toHaveProperty("voiceover_key");
  });

  it("strips only the elevenlabs prefix from voice ids", () => {
    expect(bareVoiceId("elevenlabs:abc")).toBe("abc");
    expect(bareVoiceId("abc")).toBe("abc");
  });
});

describe("pickBackground", () => {
  const clips = [
    { id: "city", available: true },
    { id: "minecraft-parkour", available: true },
    { id: "offline", available: false },
  ];

  it("prefers the preset's clip, else the first available one", () => {
    expect(pickBackground(clips, "minecraft-parkour")).toBe("minecraft-parkour");
    expect(pickBackground(clips, "offline")).toBe("city");
    expect(pickBackground(clips, "")).toBe("city");
    expect(pickBackground([], "")).toBe("");
  });
});

describe("results helpers", () => {
  it("parses at most three safe unique job ids", () => {
    expect(parseJobIds("abc123,abc123,<script>,def456,ghi789,jkl012")).toEqual([
      "abc123",
      "def456",
      "ghi789",
    ]);
    expect(parseJobIds(["abc123", "def456"])).toEqual(["abc123", "def456"]);
    expect(parseJobIds(undefined)).toEqual([]);
  });

  it("builds the results URL", () => {
    expect(resultsHref(["abc123", "def456"])).toBe("/create/results?jobs=abc123,def456");
  });

  it("derives phase, stage label and progress from a job snapshot", () => {
    expect(variantPhase(undefined)).toBe("queued");
    expect(variantPhase({ state: JobState.Processing, progress: 0 })).toBe("queued");
    expect(variantPhase({ state: JobState.Processing, progress: 20 })).toBe("rendering");
    expect(variantPhase({ state: JobState.Complete, progress: 100 })).toBe("ready");
    expect(variantPhase({ state: JobState.Failed, progress: 40 })).toBe("failed");

    expect(
      currentStageLabel({
        state: JobState.Processing,
        progress: 40,
        stages: { script: "complete", tts: "complete", avatar: "running" },
      }),
    ).toBe("Rendering the presenter");
    expect(currentStageLabel({ state: JobState.Processing, progress: 0 })).toBe(
      "Waiting for a render slot",
    );
    expect(variantProgress({ state: JobState.Processing, progress: 140 })).toBe(100);
    expect(variantProgress({ state: JobState.Complete, progress: 0 })).toBe(100);
  });

  it("formats elapsed time as m:ss", () => {
    expect(formatElapsed(0)).toBe("0:00");
    expect(formatElapsed(125_400)).toBe("2:05");
  });
});

describe("mobile helpers", () => {
  it("falls back to the talking presenter for unknown presets", () => {
    expect(resolvePreset("nope").id).toBe("talking");
    expect(resolvePreset("faceless").id).toBe("faceless");
  });

  it("reads the host of a link for the helper copy", () => {
    expect(hostOf("https://www.shop.com/p/1")).toBe("shop.com");
    expect(hostOf("not a url")).toBe("not a url");
  });

  it("reads voice ids from either field and prefers the avatar's paired voice", () => {
    const voices = [{ voice_id: "v1" }, { id: "v2" }, { name: "no id" }];
    expect(voiceIdOf(voices[1] ?? {})).toBe("v2");
    expect(voiceIdOf(voices[2] ?? {})).toBe("");
    expect(defaultVoiceFor("elevenlabs:v2", voices)).toBe("v2");
    expect(defaultVoiceFor("elevenlabs:missing", voices)).toBe("v1");
    expect(defaultVoiceFor(undefined, [])).toBe("");
  });

  it("names what the server is missing for a preset", () => {
    expect(
      missingCatalogParts({ needsPresenter: true, avatarCount: 0, voiceCount: 2, backgroundId: "x" }),
    ).toEqual(["an AI presenter"]);
    expect(
      missingCatalogParts({ needsPresenter: false, avatarCount: 0, voiceCount: 0, backgroundId: "" }),
    ).toEqual(["a narration voice", "background footage"]);
    expect(
      missingCatalogParts({ needsPresenter: true, avatarCount: 1, voiceCount: 1, backgroundId: "x" }),
    ).toEqual([]);
  });

  it("turns HTTP failures into creator-facing copy", () => {
    expect(describeCreateError(402, "")).toContain("enough credits");
    expect(describeCreateError(429, "")).toContain("Wait a few minutes");
    expect(describeCreateError(422, "Subject too long")).toBe("Subject too long");
    expect(describeCreateError(503, "")).toContain("temporarily unavailable");
    expect(describeCreateError(0, "fetch failed")).toContain("offline");
    expect(describeCreateError(500, "Boom")).toBe("Boom");
    expect(describeCreateError(undefined, "")).toBe("Something went wrong. Please try again.");
  });

  it("reports what a run actually cost, with failed renders refunded", () => {
    const cost = runCost(["ready", "failed", "rendering"]);
    expect(cost).toEqual({
      charged: 2 * CREDITS_PER_REEL,
      refunded: CREDITS_PER_REEL,
      pending: CREDITS_PER_REEL,
    });
    expect(describeRunCost(cost)).toBe(
      "2 credits charged; 1 credit of that still rendering and refunded if it fails; 1 credit refunded for failed renders.",
    );
    expect(describeRunCost(runCost(["ready", "ready", "ready"]))).toBe("3 credits charged.");
  });
});
