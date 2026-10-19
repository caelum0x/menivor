import { describe, expect, it } from "vitest";
import {
  availabilityAnswer,
  joinLabels,
  parseLaunchPosture,
  resolveLaunchPosture,
  WAITLIST_POSTURE,
} from "./posture";

const PUBLIC_FREE = {
  status: 200,
  data: {
    mode: "public",
    public_access: true,
    phase: "public",
    features: { signup: true, checkout: false, publishing: false },
    tier: "free",
    available_formats: [
      { id: "captions_only_byov", label: "Captions over your own video" },
      { id: "faceless_free_voice", label: "Faceless narrated reel with a free voice" },
    ],
    locked_formats: [{ id: "avatar_reel", label: "AI avatar reel", code: "format_locked" }],
  },
};

describe("parseLaunchPosture", () => {
  it("reads a public free-tier envelope", () => {
    const p = parseLaunchPosture(PUBLIC_FREE);
    expect(p).toMatchObject({
      mode: "public",
      signupOpen: true,
      checkoutOpen: false,
      publishingOpen: false,
    });
    expect(p?.availableFormats.map((f) => f.id)).toEqual([
      "captions_only_byov",
      "faceless_free_voice",
    ]);
    expect(p?.lockedFormats).toEqual([{ id: "avatar_reel", label: "AI avatar reel" }]);
  });

  it("accepts the bare data object", () => {
    expect(parseLaunchPosture(PUBLIC_FREE.data)?.mode).toBe("public");
  });

  it("treats public access without open signup as beta", () => {
    const raw = { public_access: true, features: { signup: false } };
    expect(parseLaunchPosture(raw)?.mode).toBe("beta");
  });

  it("treats a private beta as beta", () => {
    const raw = { phase: "private_beta", public_access: false, features: { signup: false } };
    expect(parseLaunchPosture(raw)?.mode).toBe("beta");
  });

  it("returns null for garbage", () => {
    expect(parseLaunchPosture(null)).toBeNull();
    expect(parseLaunchPosture("nope")).toBeNull();
    expect(parseLaunchPosture({ status: 500, message: "down" })).toBeNull();
  });

  it("drops malformed and duplicate formats", () => {
    const raw = {
      public_access: true,
      features: { signup: true },
      available_formats: [{ id: "a", label: "A" }, { id: "a", label: "A2" }, { id: "" }, 7],
    };
    expect(parseLaunchPosture(raw)?.availableFormats).toEqual([{ id: "a", label: "A" }]);
  });
});

describe("resolveLaunchPosture", () => {
  it("honours the waitlist override", () => {
    expect(resolveLaunchPosture(PUBLIC_FREE, true)).toBe(WAITLIST_POSTURE);
  });

  it("falls back to the waitlist posture when the status is unreadable", () => {
    expect(resolveLaunchPosture(undefined, false)).toBe(WAITLIST_POSTURE);
  });
});

describe("availabilityAnswer", () => {
  it("lists open formats and what is not open yet, with no credit counts", () => {
    const answer = availabilityAnswer(resolveLaunchPosture(PUBLIC_FREE, false));
    expect(answer).toContain("open to everyone on the free tier");
    expect(answer).toContain(
      "Open now: Captions over your own video and Faceless narrated reel with a free voice.",
    );
    expect(answer).toContain("Paid credit packs and paid formats are not on sale yet.");
    expect(answer).toContain("Publishing directly to social platforms is not available yet");
    expect(answer).not.toMatch(/\d+ (free )?reels/);
  });

  it("omits closed-feature notes once they open", () => {
    const raw = {
      ...PUBLIC_FREE.data,
      features: { signup: true, checkout: true, publishing: true },
    };
    const answer = availabilityAnswer(resolveLaunchPosture(raw, false));
    expect(answer).not.toContain("not on sale");
    expect(answer).not.toContain("Publishing directly");
    // Locked formats are never advertised, even by name (claims rule 5).
    expect(answer).not.toContain("Not available yet");
    expect(answer).not.toContain("AI avatar reel");
  });

  it("keeps the waitlist and beta wording", () => {
    expect(availabilityAnswer(WAITLIST_POSTURE)).toContain("Join the waitlist");
    const beta = resolveLaunchPosture({ phase: "private_beta", public_access: false }, false);
    expect(availabilityAnswer(beta)).toContain("Request early access");
  });
});

describe("joinLabels", () => {
  it("joins as readable English", () => {
    expect(joinLabels([])).toBe("");
    expect(joinLabels([{ id: "a", label: "A" }])).toBe("A");
    expect(
      joinLabels([
        { id: "a", label: "A" },
        { id: "b", label: "B" },
        { id: "c", label: "C" },
      ]),
    ).toBe("A, B and C");
  });
});
