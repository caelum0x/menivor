import * as React from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/lib/auth-state", () => ({ useSignedInState: () => ({ isLoaded: true, isSignedIn: true }) }));
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => async () => "session" }));
const upload = vi.hoisted(() => ({ fn: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  presignAndUpload: upload.fn,
}));

import { ApiError } from "@/src/shared/api";
import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";
import { classifyFailure, planVeryTime, startVeryTime } from "./api";
import {
  DEFAULT_SOUND,
  DEFAULT_VOICE,
  buildInput,
  changeVoice,
  extrasLabel,
  endCardLabel,
  garmentFileProblem,
  logoFileProblem,
  placeProblem,
  previewLine,
  soundBody,
  splitByTerms,
  voiceBody,
} from "./model";
import { ResultView } from "./ResultView";
import { VeryTimeWizard } from "./VeryTimeWizard";

type Route = (url: string, method: string, body: unknown) => { status: number; data: unknown };
interface Call { url: string; method: string; body: unknown; headers: Record<string, string> }

function stubApi(route: Route) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body, headers: (init?.headers ?? {}) as Record<string, string> });
      const { status, data } = route(url, method, body);
      const payload = { status, data, message: status === 200 ? "" : "refused" };
      return { ok: status === 200, status, statusText: "", headers: new Headers(),
        json: async () => payload, text: async () => JSON.stringify(payload) };
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const LINE = "You met me at a very Turkish time in my life.";
const BEATS = ["ritual_macro", "character", "detail", "wide_place", "deadpan_line"].map((beat, index) => ({
  index, beat, line: index === 4 ? LINE : "", camera: "static", seconds: [2, 3, 2.5, 3, 4.5][index] ?? 2,
}));
function planData(frames = 2, animated = 600) {
  return {
    preset: "very-time@v1", look: "console", caption_style: "game_subtitle", lines: BEATS.map((b) => b.line), beats: BEATS,
    quote: { seconds: 15, frames: { standard_credits: frames, ai_video_credits: 0 }, animated: { standard_credits: 2, ai_video_credits: animated } },
  };
}
const DONE_JOB = { job_id: "vt1", state: 1, mode: "frames", stage: "finished", frames: [], identity_score_min: null,
  video_url: "https://m/final.mp4", poster_url: "https://m/p.jpg", error: "", refunded: false };

function fillPlace(place = "Turkish", ritual = "tea poured into a tulip glass at midnight") {
  fireEvent.change(screen.getByLabelText("Your place"), { target: { value: place } });
  fireEvent.change(screen.getByLabelText("An everyday ritual from that place"), { target: { value: ritual } });
}

async function walkToPrice() {
  fillPlace();
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  fireEvent.click(await screen.findByRole("button", { name: /Console cutscene/ }));
  fireEvent.click(await screen.findByRole("button", { name: /15 seconds/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Skip" }));
  await passVoiceAndSound();
}

async function passVoiceAndSound() {
  expect(await screen.findByRole("heading", { name: "Voice" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(await screen.findByRole("heading", { name: "Sound" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
}

describe("very time api", () => {
  it("posts the plan and start bodies to the very-time routes with the session token", async () => {
    const calls = stubApi((url) => (url.endsWith("/film/very-time/plan")
      ? { status: 200, data: planData() } : { status: 200, data: { job_id: "vt1", state: 4 } }));
    const input = { place_word: "Turkish", ritual: "tea", look: "flash" as const };
    const plan = await planVeryTime(input, { token: "tok" });
    expect(plan.beats).toHaveLength(5);
    await startVeryTime({ ...input, mode: "animated", quoted: plan.quote.animated }, { token: "tok" });
    expect(calls[0]).toMatchObject({ method: "POST", body: input });
    expect(calls[0]?.url.endsWith("/api/v1/film/very-time/plan")).toBe(true);
    expect(calls[0]?.headers["x-api-key"]).toBe("tok");
    expect(calls[1]?.url.endsWith("/api/v1/film/very-time")).toBe(true);
    expect(calls[1]?.body).toEqual({ ...input, mode: "animated", quoted: { standard_credits: 2, ai_video_credits: 600 } });
  });

  it("maps guard, quote and credit errors", () => {
    const err = (status: number, data: unknown) => new ApiError("refused", status, { status, data, message: "refused" });
    expect(classifyFailure(err(400, { code: "guard_blocked", terms: ["bad", 3, "word"] }))).toEqual({ kind: "guard", terms: ["bad", "word"] });
    expect(classifyFailure(err(409, { code: "quote_changed" }))).toEqual({ kind: "quote_changed" });
    expect(classifyFailure(err(402, { code: "credits_required" }))).toEqual({ kind: "credits", aiVideo: false });
    expect(classifyFailure(err(402, { code: "ai_video_credits_required" }))).toEqual({ kind: "credits", aiVideo: true });
    expect(classifyFailure(err(400, { code: "invalid" }))).toEqual({ kind: "other" });
    expect(classifyFailure(new Error("x"))).toEqual({ kind: "other" });
  });

  it("maps errors end to end through the shared client", async () => {
    stubApi(() => ({ status: 400, data: { code: "guard_blocked", terms: ["flag"] } }));
    const failure = await planVeryTime({ place_word: "A", ritual: "b", look: "console" }).catch(classifyFailure);
    expect(failure).toEqual({ kind: "guard", terms: ["flag"] });
  });
});

describe("very time model", () => {
  it("previews the line and checks the place word", () => {
    expect(previewLine("")).toBe("You met me at a very ___ time in my life.");
    expect(previewLine("  São  Paulo ")).toBe("You met me at a very São Paulo time in my life.");
    expect(placeProblem("Türk-Alman")).toBe("");
    expect(placeProblem("日本")).toBe("");
    expect(placeProblem("Turkish!")).not.toBe("");
    expect(placeProblem("a".repeat(25))).not.toBe("");
    expect(splitByTerms("very Bad time", ["bad"])).toEqual([
      { text: "very ", blocked: false }, { text: "Bad", blocked: true }, { text: " time", blocked: false }]);
    expect(buildInput({ place: " Turkish ", ritual: " tea ", look: "atelier", brand: { garment: " ", chest_text: "Hi" } }))
      .toEqual({ place_word: "Turkish", ritual: "tea", look: "atelier", brand: { chest_text: "Hi" } });
  });
});

describe("very time flow", () => {
  it("updates the line preview as the place word changes", () => {
    stubApi(() => ({ status: 404, data: {} }));
    render(<VeryTimeWizard />);
    expect(screen.getByTestId("vt-line-preview").textContent).toBe("You met me at a very ___ time in my life.");
    fireEvent.change(screen.getByLabelText("Your place"), { target: { value: "Brazilian" } });
    expect(screen.getByTestId("vt-line-preview").textContent).toBe("You met me at a very Brazilian time in my life.");
    expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("goes place, look, skip brand, price, make, then shows the video", async () => {
    const calls = stubApi((url, method) => {
      if (url.endsWith("/film/very-time/plan")) return { status: 200, data: planData() };
      if (url.endsWith("/film/very-time") && method === "POST") return { status: 200, data: { job_id: "vt1", state: 4 } };
      if (url.endsWith("/film/story8/vt1")) return { status: 200, data: DONE_JOB };
      return { status: 404, data: {} };
    });
    render(<VeryTimeWizard />);
    await walkToPrice();
    expect(await screen.findByText("Deadpan line")).toBeTruthy();
    expect(screen.getByText(LINE)).toBeTruthy();
    expect(screen.getByTestId("vt-price-frames").textContent).toBe("2 credits");
    expect(screen.getByTestId("vt-price-animated").textContent).toBe("2 credits + 600 AI-video credits");
    fireEvent.click(screen.getByRole("button", { name: "Make it" }));
    expect(await screen.findByText("Your video is ready")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Download/ }).getAttribute("href")).toBe("https://m/final.mp4");
    expect(screen.getByRole("link", { name: /Autopost/ }).getAttribute("href")).toBe("/autopost/new");
    const plan = calls.find((c) => c.url.endsWith("/film/very-time/plan"));
    expect(plan?.body).toEqual({ place_word: "Turkish", ritual: "tea poured into a tulip glass at midnight", look: "console" });
    const start = calls.find((c) => c.url.endsWith("/film/very-time") && c.method === "POST");
    expect(start?.body).toMatchObject({ look: "console", mode: "frames", quoted: { standard_credits: 2, ai_video_credits: 0 } });
  });

  it("sends the prefilled brand when the brand step is kept", async () => {
    const calls = stubApi((url) => (url.endsWith("/film/very-time/plan") ? { status: 200, data: planData() } : { status: 404, data: {} }));
    render(<VeryTimeWizard />);
    fillPlace("Greek");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(await screen.findByRole("button", { name: /Flash lookbook/ }));
    fireEvent.click(await screen.findByRole("button", { name: /15 seconds/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Your brand/ }));
    expect((screen.getByLabelText("Words on the chest") as HTMLInputElement).value).toBe("very Greek time");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await passVoiceAndSound();
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/film/very-time/plan"))).toBe(true));
    expect(calls[0]?.body).toMatchObject({ look: "flash", brand: { chest_text: "very Greek time" } });
  });

  it("returns to step 1 and marks the blocked words on a guard refusal", async () => {
    stubApi(() => ({ status: 400, data: { code: "guard_blocked", terms: ["midnight"] } }));
    render(<VeryTimeWizard />);
    await walkToPrice();
    expect(await screen.findByText("Step 1 of 7")).toBeTruthy();
    const list = screen.getByRole("list", { name: "Words to change" });
    expect(within(list).getByText("midnight").tagName).toBe("MARK");
    const ritual = screen.getByLabelText("An everyday ritual from that place");
    expect(ritual.getAttribute("aria-invalid")).toBe("true");
    expect(document.querySelectorAll("#vt-ritual-help mark")[0]?.textContent).toBe("midnight");
  });

  it("re-plans and shows the new price when the quote changed", async () => {
    let plans = 0;
    const calls = stubApi((url, method) => {
      if (url.endsWith("/film/very-time/plan")) {
        plans += 1;
        return { status: 200, data: planData(plans === 1 ? 2 : 3) };
      }
      if (url.endsWith("/film/very-time") && method === "POST") return { status: 409, data: { code: "quote_changed" } };
      return { status: 404, data: {} };
    });
    render(<VeryTimeWizard />);
    await walkToPrice();
    fireEvent.click(await screen.findByRole("button", { name: "Make it" }));
    expect(await screen.findByText(/The price changed/)).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("vt-price-frames").textContent).toBe("3 credits"));
    expect(calls.filter((c) => c.url.endsWith("/film/very-time/plan"))).toHaveLength(2);
  });

  it("links to the top-up screen when credits are short", async () => {
    stubApi((url) => (url.endsWith("/film/very-time/plan")
      ? { status: 200, data: planData() } : { status: 402, data: { code: "ai_video_credits_required" } }));
    render(<VeryTimeWizard />);
    await walkToPrice();
    fireEvent.click(await screen.findByRole("radio", { name: /Animated/ }));
    fireEvent.click(screen.getByRole("button", { name: "Make it" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("AI-video credits");
    expect(within(alert).getByRole("link", { name: "Add credits" }).getAttribute("href")).toBe("/wallet/plans");
  });
});

describe("very time options model", () => {
  const base = { place: "Turkish", ritual: "tea", look: "console" as const, brand: null };

  it("omits every new option at its default", () => {
    expect(buildInput({ ...base, voice: DEFAULT_VOICE, sound: DEFAULT_SOUND })).toEqual({
      place_word: "Turkish", ritual: "tea", look: "console" });
    expect(voiceBody(DEFAULT_VOICE)).toBeUndefined();
    expect(soundBody(DEFAULT_SOUND)).toBeUndefined();
  });

  it("sends the garment photo, voice, sound and payoff when set", () => {
    const input = buildInput({
      ...base,
      brand: { garment_ref: "uploads/g.png" },
      voice: { engine: "eleven_v3", delivery: "quiet", reply: "  Me   too. ", takeKey: "vt-takes/u/1/take-2.mp3" },
      sound: { sfx: true, roomTone: false, payoff: "lipsync" },
    });
    expect(input).toEqual({
      place_word: "Turkish", ritual: "tea", look: "console",
      brand: { garment_ref: "uploads/g.png" },
      voice: { engine: "eleven_v3", delivery: "quiet", take_key: "vt-takes/u/1/take-2.mp3", reply_line: "Me too." },
      sound: { sfx: true, room_tone: false },
      payoff: "lipsync",
    });
  });

  it("checks the garment photo type and size", () => {
    expect(garmentFileProblem({ type: "image/png", size: 1000 })).toBe("");
    expect(garmentFileProblem({ type: "image/webp", size: 10 * 1024 * 1024 })).toBe("");
    expect(garmentFileProblem({ type: "image/gif", size: 1000 })).toMatch(/PNG, JPEG or WebP/);
    expect(garmentFileProblem({ type: "image/jpeg", size: 10 * 1024 * 1024 + 1 })).toMatch(/10 MB/);
    expect(garmentFileProblem({ type: "image/jpeg", size: 0 })).not.toBe("");
  });

  it("makes a picked take stale when the engine, delivery or reply change", () => {
    const picked = { ...DEFAULT_VOICE, takeKey: "k1" };
    expect(changeVoice(picked, { engine: "free" }).takeKey).toBe("k1");
    expect(changeVoice(picked, { engine: "eleven_v3" }).takeKey).toBeNull();
    expect(changeVoice(picked, { delivery: "warm" }).takeKey).toBeNull();
    expect(changeVoice(picked, { reply: "Hi" }).takeKey).toBeNull();
  });

  it("labels price extras only when there are some", () => {
    const plan = planData() as unknown as Parameters<typeof extrasLabel>[0];
    expect(extrasLabel(plan)).toBe("");
    const withExtras = { ...plan, quote: { ...plan.quote, extras: { voice_credits: 1, sfx_credits: 1 } } };
    expect(extrasLabel(withExtras)).toBe("Includes premium voice (+1) and sound effects (+1).");
    expect(extrasLabel({ ...plan, quote: { ...plan.quote, extras: { voice_credits: 0, sfx_credits: 0 } } })).toBe("");
  });
});

const TAKES = {
  takes: [
    { key: "vt-takes/u/t/take-1.mp3", url: "https://m/take-1.mp3", seconds: 3.1, flatness: 0.4 },
    { key: "vt-takes/u/t/take-2.mp3", url: "https://m/take-2.mp3", seconds: 3.0, flatness: 0.9 },
    { key: "vt-takes/u/t/take-3.mp3", url: "https://m/take-3.mp3", seconds: 3.3, flatness: 0.6 },
  ],
  recommended: "vt-takes/u/t/take-2.mp3",
};

async function walkToVoice() {
  fillPlace();
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  fireEvent.click(await screen.findByRole("button", { name: /Console cutscene/ }));
  fireEvent.click(await screen.findByRole("button", { name: /15 seconds/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Skip" }));
  expect(await screen.findByRole("heading", { name: "Voice" })).toBeTruthy();
}

describe("very time options flow", () => {
  it("uploads a garment photo and sends its key", async () => {
    upload.fn.mockResolvedValueOnce({ key: "uploads/abc.png", get_url: "https://m/abc.png" });
    const calls = stubApi((url) => (url.endsWith("/film/very-time/plan") ? { status: 200, data: planData() } : { status: 404, data: {} }));
    render(<VeryTimeWizard />);
    fillPlace();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(await screen.findByRole("button", { name: /Flash lookbook/ }));
    fireEvent.click(await screen.findByRole("button", { name: /15 seconds/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Your brand/ }));
    const file = new File(["x"], "shirt.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Upload your garment photo"), { target: { files: [file] } });
    expect(await screen.findByTestId("vt-garment-photo-ready")).toBeTruthy();
    expect(screen.getByRole("img", { name: "Your garment" }).getAttribute("src")).toBe("https://m/abc.png");
    expect(upload.fn).toHaveBeenCalledWith(file, { token: "session" });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await passVoiceAndSound();
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/film/very-time/plan"))).toBe(true));
    expect(calls[0]?.body).toMatchObject({ brand: { garment_ref: "uploads/abc.png" } });
  });

  it("refuses a wrong garment file without uploading", async () => {
    upload.fn.mockClear();
    stubApi(() => ({ status: 404, data: {} }));
    render(<VeryTimeWizard />);
    fillPlace();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(await screen.findByRole("button", { name: /Flash lookbook/ }));
    fireEvent.click(await screen.findByRole("button", { name: /15 seconds/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Your brand/ }));
    const file = new File(["x"], "shirt.gif", { type: "image/gif" });
    fireEvent.change(screen.getByLabelText("Upload your garment photo"), { target: { files: [file] } });
    expect((await screen.findByRole("alert")).textContent).toMatch(/PNG, JPEG or WebP/);
    expect(upload.fn).not.toHaveBeenCalled();
  });

  it("makes takes, preselects the flattest, sends the picked take and clears takes on engine change", async () => {
    const calls = stubApi((url) => {
      if (url.endsWith("/film/very-time/takes")) return { status: 200, data: TAKES };
      if (url.endsWith("/film/very-time/plan")) return { status: 200, data: planData() };
      return { status: 404, data: {} };
    });
    render(<VeryTimeWizard />);
    await walkToVoice();
    fireEvent.click(screen.getByRole("radio", { name: /Premium voice/ }));
    fireEvent.click(screen.getByRole("button", { name: "Make takes" }));
    const flattest = await screen.findByRole("radio", { name: /Take 2/ });
    expect((flattest as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText("Flattest")).toBeTruthy();
    expect(document.querySelectorAll("audio")).toHaveLength(3);
    const takesCall = calls.find((c) => c.url.endsWith("/film/very-time/takes"));
    expect(takesCall?.body).toEqual({ place_word: "Turkish", engine: "eleven_v3", delivery: "deadpan", count: 3 });
    fireEvent.click(screen.getByRole("radio", { name: /Take 3/ }));

    fireEvent.click(screen.getByRole("radio", { name: /Free voice/ }));
    expect(screen.queryByRole("radio", { name: /Take 1/ })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: /Premium voice/ }));
    fireEvent.click(screen.getByRole("button", { name: "Make takes" }));
    fireEvent.click(await screen.findByRole("radio", { name: /Take 3/ }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("heading", { name: "Sound" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/film/very-time/plan"))).toBe(true));
    const plan = calls.find((c) => c.url.endsWith("/film/very-time/plan"));
    expect(plan?.body).toMatchObject({
      voice: { engine: "eleven_v3", delivery: "deadpan", take_key: "vt-takes/u/t/take-3.mp3" } });
  });

  it("says the free voice still works when premium is unavailable", async () => {
    stubApi((url) => (url.endsWith("/film/very-time/takes")
      ? { status: 503, data: { code: "voice_unavailable" } } : { status: 404, data: {} }));
    render(<VeryTimeWizard />);
    await walkToVoice();
    fireEvent.click(screen.getByRole("radio", { name: /Premium voice/ }));
    fireEvent.click(screen.getByRole("button", { name: "Make takes" }));
    expect((await screen.findByRole("alert")).textContent)
      .toBe("Premium voice is not available right now; the free voice still works.");
  });

  it("starts with sound off and native payoff, then sends sound choices and shows extras", async () => {
    const withExtras = { ...planData(), quote: { ...planData().quote, extras: { voice_credits: 0, sfx_credits: 1 } } };
    const calls = stubApi((url) => (url.endsWith("/film/very-time/plan") ? { status: 200, data: withExtras } : { status: 404, data: {} }));
    render(<VeryTimeWizard />);
    await walkToVoice();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("heading", { name: "Sound" })).toBeTruthy();
    const sfx = screen.getByRole("checkbox", { name: /Sound effects/ }) as HTMLInputElement;
    const room = screen.getByRole("checkbox", { name: /room sound/ }) as HTMLInputElement;
    expect([sfx.checked, room.checked]).toEqual([false, false]);
    expect((screen.getByRole("radio", { name: /The video says the line/ }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(sfx);
    fireEvent.click(screen.getByRole("radio", { name: /Voice-over only/ }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect((await screen.findByTestId("vt-price-extras")).textContent).toBe("Includes sound effects (+1).");
    const plan = calls.find((c) => c.url.endsWith("/film/very-time/plan"));
    expect(plan?.body).toMatchObject({ sound: { sfx: true, room_tone: false }, payoff: "voiceover" });
  });

  it("shows the character sheet and the overlay note on the result", () => {
    render(<ResultView
      job={{ ...DONE_JOB, mode: "animated", sheet_url: "https://m/sheet.png",
        chest: [{ index: 1, status: "overlay", attempts: 3 }, { index: 4, status: "ok", attempts: 1 }] }}
      onAnother={() => undefined}
    />);
    expect(screen.getByRole("img", { name: "Character sheet" }).getAttribute("src")).toBe("https://m/sheet.png");
    expect(screen.getByTestId("vt-overlay-note").textContent).toContain("one frame");
  });

  it("shows neither when the job has no sheet or overlays", () => {
    render(<ResultView job={{ ...DONE_JOB, mode: "frames" }} onAnother={() => undefined} />);
    expect(screen.queryByRole("img", { name: "Character sheet" })).toBeNull();
    expect(screen.queryByTestId("vt-overlay-note")).toBeNull();
  });
});

describe("very time length and brand preset", () => {
  const base = { place: "Turkish", ritual: "tea", look: "console" as const, brand: null };

  it("sends the length only when it is not 15 seconds", () => {
    expect(buildInput({ ...base, duration: 15 })).not.toHaveProperty("duration_s");
    expect(buildInput(base)).not.toHaveProperty("duration_s");
    expect(buildInput({ ...base, duration: 10 })).toMatchObject({ duration_s: 10 });
    expect(buildInput({ ...base, duration: 30 })).toMatchObject({ duration_s: 30 });
  });

  it("sends only the preset for Oxhan Atelier, even with leftover custom fields", () => {
    const input = buildInput({ ...base, brand: { preset: "oxhan", garment: "x", cta: "y" }, line: "Other line." });
    expect(input.brand).toEqual({ preset: "oxhan" });
    expect(input).not.toHaveProperty("line");
  });

  it("sends a custom brand with call to action, logo and an edited closing line", () => {
    const input = buildInput({
      ...base,
      brand: { preset: "custom", chest_text: "very Turkish time", cta: "  Get yours at  shop.example ", logo_ref: "uploads/logo.png" },
      line: " Hold still. ",
    });
    expect(input.brand).toEqual({ chest_text: "very Turkish time", cta: "Get yours at shop.example", logo_ref: "uploads/logo.png" });
    expect(input.line).toBe("Hold still.");
    const unchanged = buildInput({ ...base, brand: { preset: "custom" }, line: previewLine("Turkish") });
    expect(unchanged).not.toHaveProperty("line");
  });

  it("checks the logo file type and size", () => {
    expect(logoFileProblem({ type: "image/png", size: 5 * 1024 * 1024 })).toBe("");
    expect(logoFileProblem({ type: "image/svg+xml", size: 100 })).toMatch(/PNG, JPEG or WebP logo/);
    expect(logoFileProblem({ type: "image/jpeg", size: 5 * 1024 * 1024 + 1 })).toBe("Keep the logo under 5 MB.");
  });

  it("labels the end card only when it has a call to action", () => {
    const plan = planData() as unknown as Parameters<typeof endCardLabel>[0];
    expect(endCardLabel(plan)).toBe("");
    expect(endCardLabel(null)).toBe("");
    const withCard = { ...planData(), end_card: { cta: "Get yours at oxhanatelier.com", logo: true, seconds: 1.5 } };
    expect(endCardLabel(withCard as unknown as Parameters<typeof endCardLabel>[0]))
      .toBe("Ends with: Get yours at oxhanatelier.com");
  });
});

describe("very time length and brand flow", () => {
  async function toBrand(length: RegExp) {
    fillPlace();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(await screen.findByRole("button", { name: /Console cutscene/ }));
    expect(screen.getByRole("button", { name: /15 seconds/ }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: length }));
    expect(await screen.findByRole("heading", { name: "Your brand" })).toBeTruthy();
  }

  it("picks Oxhan Atelier and 30 seconds, and shows the end card on the price step", async () => {
    const oxhanPlan = { ...planData(), duration_s: 30, brand_preset: "oxhan",
      end_card: { cta: "Get yours at oxhanatelier.com", logo: true, seconds: 1.5 } };
    const calls = stubApi((url) => (url.endsWith("/film/very-time/plan") ? { status: 200, data: oxhanPlan } : { status: 404, data: {} }));
    render(<VeryTimeWizard />);
    await toBrand(/30 seconds/);
    expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /Oxhan Atelier/ }));
    expect(screen.getByTestId("vt-oxhan-summary").textContent).toContain("Get yours at oxhanatelier.com");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await passVoiceAndSound();
    expect((await screen.findByTestId("vt-end-card")).textContent).toBe("Ends with: Get yours at oxhanatelier.com");
    const plan = calls.find((c) => c.url.endsWith("/film/very-time/plan"));
    expect(plan?.body).toEqual({ place_word: "Turkish", ritual: "tea poured into a tulip glass at midnight",
      look: "console", brand: { preset: "oxhan" }, duration_s: 30 });
  });

  it("sends a custom brand with a closing line, call to action and logo", async () => {
    upload.fn.mockReset();
    upload.fn.mockResolvedValueOnce({ key: "uploads/logo.png", get_url: "https://m/logo.png" });
    const calls = stubApi((url) => (url.endsWith("/film/very-time/plan") ? { status: 200, data: planData() } : { status: 404, data: {} }));
    render(<VeryTimeWizard />);
    await toBrand(/10 seconds/);
    fireEvent.click(screen.getByRole("button", { name: /Your brand/ }));
    const line = screen.getByLabelText("Closing line") as HTMLInputElement;
    expect(line.value).toBe(LINE);
    fireEvent.change(line, { target: { value: "Hold still. I'm not finished." } });
    const cta = screen.getByLabelText("Call to action on the end card") as HTMLInputElement;
    expect(cta.placeholder).toBe("Get yours at yourshop.com");
    fireEvent.change(cta, { target: { value: "Get yours at shop.example" } });
    const bad = new File(["x"], "logo.svg", { type: "image/svg+xml" });
    fireEvent.change(screen.getByLabelText("Upload your logo"), { target: { files: [bad] } });
    expect((await screen.findByRole("alert")).textContent).toMatch(/PNG, JPEG or WebP logo/);
    expect(upload.fn).not.toHaveBeenCalled();
    const logo = new File(["x"], "logo.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Upload your logo"), { target: { files: [logo] } });
    expect(await screen.findByTestId("vt-logo-ready")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await passVoiceAndSound();
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/film/very-time/plan"))).toBe(true));
    const plan = calls.find((c) => c.url.endsWith("/film/very-time/plan"));
    expect(plan?.body).toMatchObject({
      duration_s: 10, line: "Hold still. I'm not finished.",
      brand: { chest_text: "very Turkish time", cta: "Get yours at shop.example", logo_ref: "uploads/logo.png" },
    });
    expect((plan?.body as { brand: Record<string, unknown> }).brand).not.toHaveProperty("preset");
  });

  it("shows the end card on the result", () => {
    render(<ResultView job={{ ...DONE_JOB, mode: "frames" }} onAnother={() => undefined} endCta="Get yours at oxhanatelier.com" />);
    expect(screen.getByTestId("vt-result-end-card").textContent).toBe("Ends with: Get yours at oxhanatelier.com");
  });
});

const NEW_FILES = [
  "app/very-time/page.tsx",
  "src/features/very-time/api.ts",
  "src/features/very-time/model.ts",
  "src/features/very-time/index.ts",
  "src/features/very-time/ResultView.tsx",
  "src/features/very-time/VeryTimeWizard.tsx",
  "src/features/very-time/steps/PlaceStep.tsx",
  "src/features/very-time/steps/LookStep.tsx",
  "src/features/very-time/steps/BrandStep.tsx",
  "src/features/very-time/steps/PriceStep.tsx",
  "src/features/very-time/steps/VoiceStep.tsx",
  "src/features/very-time/steps/SoundStep.tsx",
  "src/features/very-time/steps/LengthStep.tsx",
  "src/features/very-time/steps/ImageUploadField.tsx",
  "src/features/very-time/very-time.test.tsx",
];

describe("very time copy", () => {
  const web = process.cwd();
  const read = (rel: string) => fs.readFileSync(path.join(web, rel), "utf8");

  it("has no emoji in any new file", () => {
    const emoji = /[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}\u{FE0F}]/u;
    for (const rel of NEW_FILES) expect([rel, emoji.test(read(rel))]).toEqual([rel, false]);
  });

  it("passes the copy denylist", () => {
    const denylist = JSON.parse(fs.readFileSync(path.resolve(web, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
    const units = NEW_FILES.filter((f) => !f.endsWith(".test.tsx")).flatMap((rel) => sourceUnits(read(rel), rel).units);
    expect(checkUnits(denylist, units, { flags: {} }).filter((h) => h.severity === "error")).toEqual([]);
  });
});
