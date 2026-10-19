/**
 * Unit tests for the Reel Compose pure logic: template→job translation, input
 * validation, default seeding, layout coercion, and review-phase derivation.
 * No network, no renderer — pure functions only.
 */

import { describe, expect, it } from "vitest";
import {
  buildJobRequest,
  catalogVoiceSelector,
  coerceLayout,
  defaultInputValues,
  missingRequiredInputs,
  reviewPhase,
} from "../logic";
import type { ReelDraft, TemplateInputDef } from "@/lib/templates";
import { JobState } from "@/lib/types";

const draft: ReelDraft = {
  video_subject: "  Cozy rain ASMR  ",
  video_script: "  soft whispers  ",
  layout: "split",
  caption_style: "bold",
  camera_motion: "slow_push",
  music_prompt: "  lofi rain  ",
  effects: ["grain"],
  screen_recording_key: "uploads/rec.mp4",
};

describe("catalogVoiceSelector", () => {
  it("prefixes a raw voice id with the ElevenLabs selector", () => {
    expect(catalogVoiceSelector("v123")).toBe("elevenlabs:v123");
  });
});

describe("coerceLayout", () => {
  it("keeps a known layout", () => {
    expect(coerceLayout("split")).toBe("split");
  });
  it("falls back for an unknown layout", () => {
    expect(coerceLayout("nonsense")).toBe("pip");
    expect(coerceLayout("nonsense", "hook_intro")).toBe("hook_intro");
  });
});

describe("buildJobRequest", () => {
  const req = buildJobRequest({
    draft,
    avatarId: "av_1",
    voiceId: "v9",
    recordingKey: "uploads/rec.mp4",
    durationS: 45,
  });

  it("trims the subject/script and carries the template creative direction", () => {
    expect(req.params.video_subject).toBe("Cozy rain ASMR");
    expect(req.params.video_script).toBe("soft whispers");
    expect(req.params.layout).toBe("split");
    expect(req.params.caption_style).toBe("bold");
    expect(req.params.target_duration_s).toBe(45);
    expect(req.params.aspect).toBe("9:16");
  });

  it("wires the creator's avatar/voice/recording into the request", () => {
    expect(req.params.avatar_id).toBe("av_1");
    expect(req.avatar_id).toBe("av_1");
    expect(req.params.voice_name).toBe("elevenlabs:v9");
    expect(req.voice_id).toBe("v9");
    expect(req.params.screen_recording_key).toBe("uploads/rec.mp4");
  });

  it("forwards a non-empty music prompt and camera motion", () => {
    expect(req.music_prompt).toBe("lofi rain");
    expect(req.camera_motion).toBe("slow_push");
  });

  it("omits empty optional fields", () => {
    const bare = buildJobRequest({
      draft: {
        video_subject: "x",
        video_script: "",
        layout: "pip",
        caption_style: "",
        camera_motion: "none",
        music_prompt: "",
      },
      avatarId: "a",
      voiceId: "v",
      recordingKey: "k",
      durationS: 20,
    });
    expect(bare.params.video_script).toBeUndefined();
    expect(bare.music_prompt).toBeUndefined();
    expect(bare.camera_motion).toBeUndefined();
    expect(bare.params.caption_style).toBe("default");
  });
});

describe("missingRequiredInputs", () => {
  const inputs: TemplateInputDef[] = [
    { key: "hook", kind: "text", label: "Hook", required: true, help: "", choices: [], default: "" },
    { key: "cta", kind: "text", label: "CTA", required: false, help: "", choices: [], default: "" },
  ];

  it("flags empty required inputs only", () => {
    expect(missingRequiredInputs(inputs, {})).toEqual(["hook"]);
    expect(missingRequiredInputs(inputs, { hook: "  " })).toEqual(["hook"]);
    expect(missingRequiredInputs(inputs, { hook: "Wait for it" })).toEqual([]);
  });
});

describe("defaultInputValues", () => {
  it("seeds string defaults and blanks non-string defaults", () => {
    const inputs: TemplateInputDef[] = [
      { key: "hook", kind: "text", label: "H", required: true, help: "", choices: [], default: "Hi" },
      { key: "n", kind: "number", label: "N", required: false, help: "", choices: [], default: 5 },
    ];
    expect(defaultInputValues(inputs)).toEqual({ hook: "Hi", n: "" });
  });
});

describe("reviewPhase", () => {
  it("maps terminal + progress states to review phases", () => {
    expect(reviewPhase(JobState.Failed, 0.5)).toBe("failed");
    expect(reviewPhase(JobState.Complete, 1)).toBe("completed");
    expect(reviewPhase(JobState.Processing, 0)).toBe("queued");
    expect(reviewPhase(JobState.Processing, 0.4)).toBe("running");
  });
});
