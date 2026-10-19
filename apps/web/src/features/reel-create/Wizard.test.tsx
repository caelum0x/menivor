import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { DEFAULT_WIZARD_STATE } from "@/components/wizard/types";
import { buildRequest, routeForCreateResult, Wizard } from "./Wizard";

const mocks = vi.hoisted(() => ({
  clearBrollAttachment: vi.fn(),
  createJob: vi.fn(),
  getApiToken: vi.fn(async () => "api-token"),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/use-api-token", () => ({
  useApiToken: () => mocks.getApiToken,
}));
// Mutable so individual tests can exercise the capability-denied card.
const capabilityMock = vi.hoisted(() => ({
  state: {
    capabilities: { generation: { reels: true, broll: true }, mode: "pilot" },
    loading: false,
    error: "",
  } as { capabilities: object | null; loading: boolean; error: string },
}));
const ALLOWED_CAPABILITY_STATE = capabilityMock.state;

vi.mock("@/lib/use-generation-capabilities", () => ({
  useGenerationCapabilities: () => capabilityMock.state,
}));
vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  createJob: mocks.createJob,
}));
const formatMock = vi.hoisted(() => ({
  state: { availability: null as object | null, loading: false },
}));
vi.mock("@/src/shared/launch/use-format-availability", () => ({
  useFormatAvailability: () => formatMock.state,
}));
vi.mock("@/lib/spark-prefill", () => ({ takeSparkPrefill: () => null }));
vi.mock("@/src/shared/media", () => ({
  clearBrollAttachment: mocks.clearBrollAttachment,
  loadBrollAttachment: () => null,
}));

vi.mock("./components/TemplateGallery", () => ({ TemplateGallery: () => <div /> }));
vi.mock("./components/UploadDropzone", () => ({
  UploadDropzone: ({ onUploaded }: { onUploaded: (value: object) => void }) => (
    <button
      type="button"
      onClick={() => onUploaded({ key: "uploads/source.mp4", url: "https://media/source", name: "source.mp4" })}
    >
      Mock upload
    </button>
  ),
}));
vi.mock("./components/ScriptPromptField", () => ({
  ScriptPromptField: ({ onChange }: { onChange: (value: object) => void }) => (
    <button type="button" onClick={() => onChange({ videoSubject: "Launch demo" })}>
      Mock script
    </button>
  ),
}));
vi.mock("@/components/wizard/AvatarPicker", () => ({
  AvatarPicker: ({ onSelect }: { onSelect: (value: string) => void }) => (
    <button type="button" onClick={() => onSelect("avatar-1")}>Mock avatar</button>
  ),
}));
vi.mock("@/components/voiceover/VoiceStep", () => ({
  VoiceStep: ({ onSelectVoice }: { onSelectVoice: (id: string, label: string) => void }) => (
    <button type="button" onClick={() => onSelectVoice("voice-1", "Voice One")}>Mock voice</button>
  ),
}));
vi.mock("./components/LayoutPicker", () => ({ LayoutPicker: () => <div /> }));
vi.mock("./components/CaptionStylePicker", () => ({ CaptionStylePicker: () => <div /> }));
vi.mock("./components/MusicPicker", () => ({ MusicPicker: () => <div /> }));
vi.mock("./components/VariantsSelector", () => ({ VariantsSelector: () => <div /> }));
vi.mock("./components/AutoTightenToggle", () => ({ AutoTightenToggle: () => <div /> }));
vi.mock("./components/EditingPolishSection", () => ({ EditingPolishSection: () => <div /> }));
vi.mock("./components/ChargeToSelector", () => ({ ChargeToSelector: () => <div /> }));
vi.mock("./components/ProfilePicker", () => ({ ProfilePicker: () => <div /> }));
vi.mock("./components/EffectsPicker", () => ({
  EffectsPicker: ({ onChange }: { onChange: (motion: string, effects: string[]) => void }) => (
    <button type="button" onClick={() => onChange("push_in", ["film_grain"])}>
      Mock effect change
    </button>
  ),
}));
vi.mock("@/components/presets/SavePresetButton", () => ({ SavePresetButton: () => <div /> }));

function advanceToReview(): void {
  fireEvent.click(screen.getByRole("button", { name: /continue/i }));
  fireEvent.click(screen.getByRole("button", { name: /mock upload/i }));
  fireEvent.click(screen.getByRole("button", { name: /continue/i }));
  fireEvent.click(screen.getByRole("button", { name: /mock script/i }));
  fireEvent.click(screen.getByRole("button", { name: /continue/i }));
  fireEvent.click(screen.getByRole("button", { name: /mock avatar/i }));
  fireEvent.click(screen.getByRole("button", { name: /continue/i }));
  fireEvent.click(screen.getByRole("button", { name: /mock voice/i }));
  for (let step = 0; step < 4; step += 1) {
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
  }
}

beforeEach(() => {
  mocks.clearBrollAttachment.mockReset();
  mocks.createJob.mockReset();
  mocks.getApiToken.mockClear();
  mocks.push.mockReset();
  capabilityMock.state = ALLOWED_CAPABILITY_STATE;
  formatMock.state = { availability: null, loading: false };
  vi.stubGlobal("crypto", { randomUUID: vi.fn(() => `uuid-${Math.random()}`) });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("reel create command", () => {
  it("assembles mutually exclusive voice/music and optional wallet fields", () => {
    const request = buildRequest({
      ...DEFAULT_WIZARD_STATE,
      screenRecordingKey: "uploads/source.mp4",
      videoSubject: "  Product launch  ",
      prompt: "  Exact script  ",
      avatarId: "avatar-1",
      voiceId: "ignored-voice",
      useOwnVoiceover: true,
      voiceoverKey: "uploads/voice.wav",
      musicId: "ignored-track",
      musicPrompt: "  tense synth  ",
      bgmProvider: "suno",
      workspaceId: "workspace-1",
      generationProfileId: "premium-video",
      generationQuote: { quote_id: "quote-1", max_cost_micros: 5000 },
      variants: 3,
      effects: ["film_grain"],
    });

    expect(request.params.video_subject).toBe("Product launch");
    expect(request.params.video_script).toBe("Exact script");
    expect(request.params.voice_name).toBe("");
    expect(request.voice_id).toBeUndefined();
    expect(request.voiceover_key).toBe("uploads/voice.wav");
    expect(request.music_id).toBeUndefined();
    expect(request.music_prompt).toBe("tense synth");
    expect(request.bgm_provider).toBe("suno");
    expect(request.workspace_id).toBe("workspace-1");
    expect(request.generation_profile_id).toBe("premium-video");
    expect(request.quote).toEqual({ quote_id: "quote-1", max_cost_micros: 5000 });
    expect(request.variants).toBe(3);
    expect(request.effects).toEqual(["film_grain"]);
  });

  it("encodes server-returned identifiers before navigation", () => {
    expect(routeForCreateResult({ job_id: "job/one", state: 0, progress: 0 })).toBe(
      "/jobs/job%2Fone",
    );
    expect(
      routeForCreateResult({
        job_id: "job-1",
        job_ids: ["job-1", "job-2"],
        batch_id: "batch/one",
        state: 0,
        progress: 0,
      }),
    ).toBe("/batch/batch%2Fone");
  });

  it("is single-flight and clears the handoff only after accepted creation", async () => {
    let accept: ((value: object) => void) | undefined;
    mocks.createJob.mockImplementation(() => new Promise((resolve) => { accept = resolve; }));
    render(<Wizard />);
    advanceToReview();

    const submit = screen.getByRole("button", { name: /create reel/i });
    fireEvent.click(submit);
    fireEvent.click(submit);
    await waitFor(() => expect(mocks.createJob).toHaveBeenCalledOnce());
    expect(mocks.clearBrollAttachment).not.toHaveBeenCalled();

    accept?.({ job_id: "job/accepted", state: 0, progress: 0 });
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs/job%2Faccepted"));
    expect(mocks.clearBrollAttachment).toHaveBeenCalledOnce();
  });

  it("reuses an exact failed command key and rotates it after the command changes", async () => {
    mocks.createJob.mockRejectedValue(new Error("network failure"));
    render(<Wizard />);
    advanceToReview();

    fireEvent.click(screen.getByRole("button", { name: /create reel/i }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /create reel/i }));
    await waitFor(() => expect(mocks.createJob).toHaveBeenCalledTimes(2));
    const firstKey = mocks.createJob.mock.calls[0]?.[1]?.idempotencyKey;
    expect(mocks.createJob.mock.calls[1]?.[1]?.idempotencyKey).toBe(firstKey);
    expect(mocks.clearBrollAttachment).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /mock effect change/i }));
    fireEvent.click(screen.getByRole("button", { name: /create reel/i }));
    await waitFor(() => expect(mocks.createJob).toHaveBeenCalledTimes(3));
    expect(mocks.createJob.mock.calls[2]?.[1]?.idempotencyKey).not.toBe(firstKey);
  });

  it("offers the launch-updates and demo links when generation is unavailable", () => {
    capabilityMock.state = {
      capabilities: { generation: { reels: false, broll: false }, mode: "pilot" },
      loading: false,
      error: "",
    };
    render(<Wizard />);

    expect(
      screen.getByText(/reel generation is not available for this account/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /get launch updates/i }),
    ).toHaveAttribute("href", "/#waitlist");
    expect(
      screen.getByRole("link", { name: /see sample reels/i }),
    ).toHaveAttribute("href", "/styles");
  });

  it("names a 402 format_locked format and does not offer credit packs", async () => {
    mocks.createJob.mockRejectedValue(
      Object.assign(new Error("req: This format is not available yet"), {
        status: 402,
        detail: {
          status: 402,
          data: {
            code: "format_locked",
            format: "avatar_reel",
            reason: "heygen avatar provider is not configured; use the captions_only layout",
          },
        },
      }),
    );
    render(<Wizard />);
    advanceToReview();
    fireEvent.click(screen.getByRole("button", { name: /create reel/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/AI avatar reel is not available on this server yet/i);
    expect(alert).toHaveTextContent(/heygen avatar provider is not configured/i);
    expect(alert).not.toHaveTextContent(/out of credits/i);
    expect(screen.queryByRole("link", { name: /view credit packs/i })).not.toBeInTheDocument();
  });

  it("keeps the credit-pack path for a real credit shortfall", async () => {
    mocks.createJob.mockRejectedValue(
      Object.assign(new Error("req: insufficient credits: balance 0"), {
        status: 402,
        detail: { status: 402, message: "req: insufficient credits: balance 0" },
      }),
    );
    render(<Wizard />);
    advanceToReview();
    fireEvent.click(screen.getByRole("button", { name: /create reel/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/out of credits/i);
    expect(screen.getByRole("link", { name: /view credit packs/i })).toBeInTheDocument();
  });

  it("blocks submit with the reason when the server locks AI avatar reels", () => {
    formatMock.state = {
      availability: {
        available: ["captions_only_byov"],
        locked: {
          avatar_reel: {
            id: "avatar_reel",
            label: "AI avatar reel (pip, hook_intro, split layouts)",
            reason: "no AI avatar provider is configured",
          },
        },
      },
      loading: false,
    };
    render(<Wizard />);
    expect(screen.getAllByText(/no AI avatar provider is configured/i).length).toBeGreaterThan(0);
    expect(
      screen.getByRole("link", { name: /captioned reel from your own narration/i }),
    ).toHaveAttribute("href", "/create/advanced");
    advanceToReview();
    fireEvent.click(screen.getByRole("button", { name: /create reel/i }));
    expect(screen.getByRole("button", { name: /create reel/i })).toBeDisabled();
    expect(mocks.createJob).not.toHaveBeenCalled();
  });
});
