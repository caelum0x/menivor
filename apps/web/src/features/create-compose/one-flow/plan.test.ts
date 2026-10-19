import { presenterLive } from "@/lib/styles/catalog";
import { describe, expect, it } from "vitest";
import { JobState } from "@/lib/types";
import {
  VARIANT_COUNT,
  bareVoiceId,
  HOOK_ANGLES,
  buildJobRequest,
  buildLinkBody,
  buildRunRegistration,
  hookStyleLabel,
  isHookStyle,
  topicRunVariants,
  currentStageLabel,
  formatEta,
  renderingEtaLabel,
  defaultPresetFor,
  findPreset,
  formatElapsed,
  parseJobIds,
  parseSource,
  pickBackground,
  planLinkVariants,
  planStyleVariants,
  storySubject,
  CLASSIC_PRESETS,
  STYLE_PRESETS,
  resultsHref,
  variantPhase,
  variantProgress,
} from "./plan";

describe("parseSource", () => {
  it("returns null for empty input", () => {
    expect(parseSource("   ")).toBeNull();
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
    expect(currentStageLabel({ state: JobState.Processing, progress: 0 })).toBe("Starting soon");
    expect(
      currentStageLabel({ state: JobState.Processing, progress: 0, queue: { ahead: 0, eta_s: null } }),
    ).toBe("Next in line.");
    expect(
      currentStageLabel({ state: JobState.Processing, progress: 0, queue: { ahead: 2, eta_s: 250 } }),
    ).toBe("2 reels ahead of yours. Ready in about 4 min.");
    expect(
      currentStageLabel({ state: JobState.Processing, progress: 0, queue: { ahead: 1, eta_s: 40 } }),
    ).toBe("1 reel ahead of yours. Ready in less than a minute.");
    expect(variantProgress({ state: JobState.Processing, progress: 140 })).toBe(100);
    expect(variantProgress({ state: JobState.Complete, progress: 0 })).toBe(100);
  });

  it("formats elapsed time as m:ss", () => {
    expect(formatElapsed(0)).toBe("0:00");
    expect(formatElapsed(125_400)).toBe("2:05");
  });
});

describe("one-click styles", () => {
  it("offers every style as a preset that carries its API style id", () => {
    expect(STYLE_PRESETS.map((preset) => preset.id)).toContain("meme_hook");
    for (const preset of STYLE_PRESETS) {
      expect(preset.style).toBe(preset.id);
      expect(preset.hookFamily?.length).toBeGreaterThan(0);
    }
    expect(CLASSIC_PRESETS.every((preset) => !preset.style)).toBe(true);
    expect(findPreset("gameplay_split")?.layout).toBe("captions_only");
    expect(findPreset("gameplay_split")?.needsPresenter).toBe(false);
    // Presenter styles are offered only while the presenter capability is live.
    expect(findPreset("greenscreen")?.needsPresenter ?? presenterLive()).toBe(presenterLive());
  });

  it("accepts the meme hook formats as hook styles", () => {
    expect(isHookStyle("met_me_at")).toBe(true);
    expect(isHookStyle("nobody_me")).toBe(true);
    expect(hookStyleLabel("wish_i_knew")).toBe("Wish-I-knew hook");
  });

  it("writes one script per API hook with the same page body", () => {
    const content = {
      title: "Scribase",
      description: "The backend for your apps.",
      features: ["Branch a database per task"],
    };
    const plans = planStyleVariants(content, "en", [
      { hook_style: "met_me_at", hook: "You met me at a very database-less time in my life." },
      { hook_style: "bogus", hook: "skip me" },
      { hook_style: "nobody_me", hook: "   " },
      { hook_style: "wish_i_knew", hook: "Things I wish I knew before wiring auth." },
    ]);
    expect(plans.map((plan) => plan.angle)).toEqual(["met_me_at", "wish_i_knew"]);
    const bodies = plans.map((plan) => plan.script.split("\n\n").slice(1).join("|"));
    expect(new Set(bodies).size).toBe(1);
    expect(plans[0]?.script.startsWith("You met me at a very")).toBe(true);
  });

  it("sends the style and the pasted page with the job", () => {
    const request = buildJobRequest({
      subject: "Scribase",
      script: "POV: hi",
      layout: "captions_only",
      avatarId: "",
      voiceId: "v1",
      backgroundId: "block-runner",
      language: "en",
      style: "gameplay_split",
      sourceUrl: "https://scribase.com",
    });
    const params = request.params as unknown as Record<string, unknown>;
    expect(params.style).toBe("gameplay_split");
    expect(params.source_url).toBe("https://scribase.com");
    const plain = buildJobRequest({
      subject: "x",
      layout: "pip",
      avatarId: "a",
      voiceId: "v",
      backgroundId: "",
      language: "en",
    });
    expect((plain.params as unknown as Record<string, unknown>).style).toBeUndefined();
  });
});

describe("story styles", () => {
  it("marks story styles so link runs let the API write the story", () => {
    expect(findPreset("story_gameplay")?.scriptMode).toBe("story");
    expect(findPreset("character_story")?.scriptMode).toBe("story");
    expect(findPreset("meme_hook")?.scriptMode).toBe("page");
  });

  it("builds a bounded story subject from the page", () => {
    expect(storySubject({ title: "Scribase", description: "Backend  for apps", features: [] }, "x")).toBe(
      "Scribase: Backend for apps",
    );
    expect(storySubject({ title: "", description: "", features: [] }, "scribase.com")).toBe("scribase.com");
    expect(storySubject({ title: "T", description: "d".repeat(500), features: [] }, "x").length).toBeLessThanOrEqual(201);
  });
});

describe("queue ETA labels", () => {
  it("never invents an estimate", () => {
    expect(formatEta(null)).toBe("");
    expect(formatEta(0)).toBe("");
    expect(formatEta(Number.NaN)).toBe("");
    expect(formatEta(90)).toBe("about 2 min");
    expect(formatEta(60)).toBe("about 1 min");
  });

  it("shows a measured hint only while rendering", () => {
    expect(renderingEtaLabel({ state: JobState.Processing, progress: 30, queue: { ahead: 0, eta_s: 120 } })).toBe(
      "Ready in about 2 min",
    );
    expect(renderingEtaLabel({ state: JobState.Processing, progress: 30, queue: { ahead: 0, eta_s: null } })).toBe("");
    expect(renderingEtaLabel({ state: JobState.Processing, progress: 0, queue: { ahead: 0, eta_s: 120 } })).toBe("");
    expect(renderingEtaLabel({ state: JobState.Complete, progress: 100 })).toBe("");
  });
});
