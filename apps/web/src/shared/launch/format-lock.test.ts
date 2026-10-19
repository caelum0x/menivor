import { describe, expect, it } from "vitest";
import { ApiError } from "@/src/shared/api";
import {
  firstLock,
  formatLockOf,
  formatLockedMessage,
  isCreditShortfall,
  parseFormatAvailability,
  requiredReelFormats,
} from "./format-lock";

const STATUS = {
  mode: "internal_pilot",
  available_formats: [
    { id: "captions_only_byov", label: "Captions over your own video" },
    { id: "faceless_free_voice", label: "Faceless narrated reel with a free voice" },
  ],
  locked_formats: [
    {
      id: "avatar_reel",
      label: "AI avatar reel (pip, hook_intro, split layouts)",
      code: "format_locked",
      reason: "no AI avatar provider is configured",
      unlock_env: ["HEYGEN_API_KEY"],
    },
    { id: "generated_script", label: "AI-written script", reason: "no script LLM is configured" },
    { id: "", label: "junk" },
    "not-an-object",
  ],
};

function lockedError(format: string, reason: string): ApiError {
  return new ApiError("req-1: This format is not available yet", 402, {
    status: 402,
    message: "req-1: This format is not available yet",
    data: { code: "format_locked", format, reason },
  });
}

describe("parseFormatAvailability", () => {
  it("reads available ids and locked formats with reasons, skipping junk", () => {
    const availability = parseFormatAvailability(STATUS);
    expect(availability?.available).toEqual(["captions_only_byov", "faceless_free_voice"]);
    expect(Object.keys(availability?.locked ?? {})).toEqual(["avatar_reel", "generated_script"]);
    expect(availability?.locked.avatar_reel?.reason).toBe("no AI avatar provider is configured");
  });

  it("returns null for an API without format lists (every option stays enabled)", () => {
    expect(parseFormatAvailability({ mode: "public" })).toBeNull();
    expect(parseFormatAvailability(null)).toBeNull();
    expect(parseFormatAvailability("nope")).toBeNull();
  });

  it("falls back to a readable label and reason", () => {
    const availability = parseFormatAvailability({ locked_formats: [{ id: "ai_broll" }] });
    expect(availability?.locked.ai_broll).toEqual({
      id: "ai_broll",
      label: "AI video",
      reason: "it is not set up on this server",
    });
  });
});

describe("requiredReelFormats", () => {
  it("avatar layouts need the avatar provider, a script LLM without a typed script, and TTS", () => {
    expect(requiredReelFormats({ layout: "pip", hasTypedScript: false, hasVoice: true })).toEqual([
      "avatar_reel",
      "generated_script",
      "faceless_free_voice",
    ]);
  });

  it("a typed script and an uploaded voiceover drop the LLM and TTS needs", () => {
    expect(
      requiredReelFormats({ layout: "split", hasTypedScript: true, hasVoiceover: true }),
    ).toEqual(["avatar_reel"]);
  });

  it("captions over your own narration needs nothing paid", () => {
    expect(
      requiredReelFormats({ layout: "captions_only", hasTypedScript: false, hasVoiceover: true }),
    ).toEqual([]);
  });

  it("a faceless reel needs a free voice, plus the LLM when no script is typed", () => {
    expect(
      requiredReelFormats({ layout: "captions_only", hasTypedScript: false, hasVoice: true }),
    ).toEqual(["generated_script", "faceless_free_voice"]);
    expect(
      requiredReelFormats({ layout: "captions_only", hasTypedScript: true, hasVoice: true }),
    ).toEqual(["faceless_free_voice"]);
  });

  it("a usable ElevenLabs voice needs no free TTS fallback", () => {
    expect(
      requiredReelFormats({
        layout: "captions_only",
        hasTypedScript: true,
        hasVoice: true,
        premiumVoiceUsable: true,
      }),
    ).toEqual([]);
  });
});

describe("firstLock", () => {
  it("returns the first locked requirement in order", () => {
    const availability = parseFormatAvailability(STATUS);
    expect(firstLock(availability, ["faceless_free_voice", "generated_script"])?.id).toBe(
      "generated_script",
    );
    expect(firstLock(availability, ["captions_only_byov"])).toBeNull();
  });

  it("never blocks when availability is unknown", () => {
    expect(firstLock(null, ["avatar_reel"])).toBeNull();
  });
});

describe("402 classification", () => {
  it("recognizes format_locked and names the format", () => {
    const err = lockedError("avatar_reel", "heygen avatar provider is not configured");
    const lock = formatLockOf(err);
    expect(lock).toEqual({
      format: "avatar_reel",
      label: "AI avatar reel",
      reason: "heygen avatar provider is not configured",
    });
    expect(isCreditShortfall(err)).toBe(false);
    const message = formatLockedMessage(lock!);
    expect(message).toContain("AI avatar reel");
    expect(message).toContain("heygen avatar provider is not configured");
    expect(message).not.toMatch(/enough credits|out of credits/i);
  });

  it("treats any other 402 as a credit shortfall", () => {
    const err = new ApiError("req-2: insufficient credits: balance 0", 402, {
      status: 402,
      message: "req-2: insufficient credits: balance 0",
    });
    expect(formatLockOf(err)).toBeNull();
    expect(isCreditShortfall(err)).toBe(true);
  });

  it("ignores non-402 errors and non-errors", () => {
    expect(isCreditShortfall(new ApiError("nope", 500))).toBe(false);
    expect(formatLockOf(new Error("x"))).toBeNull();
    expect(isCreditShortfall(undefined)).toBe(false);
  });
});
