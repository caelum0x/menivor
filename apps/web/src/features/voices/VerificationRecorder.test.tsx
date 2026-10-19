import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VerificationRecorder, type VerificationTake } from "@/components/voices/VerificationRecorder";

const phrase = (text: string) => ({ token: `tok-${text}`, phrase: text, expires_at: 0, required: true });

class FakeRecorder {
  static isTypeSupported = () => true;
  mimeType = "audio/webm";
  state = "inactive";
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor(public stream: { getTracks: () => { stop: () => void }[] }) {}
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/webm" }) });
    this.onstop?.();
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("VerificationRecorder (M7.2)", () => {
  it("shows a phrase and fetches a new one on request", async () => {
    const loadPhrase = vi.fn().mockResolvedValueOnce(phrase("river copper lantern")).mockResolvedValueOnce(phrase("tiger violin meadow"));
    render(<VerificationRecorder loadPhrase={loadPhrase} value={null} onChange={() => {}} />);
    await screen.findByText("river copper lantern");
    fireEvent.click(screen.getByRole("button", { name: /new phrase/i }));
    await screen.findByText("tiger violin meadow");
    expect(loadPhrase).toHaveBeenCalledTimes(2);
  });

  it("records the phrase live and reports the take with its token", async () => {
    const tracks = [{ stop: vi.fn() }];
    vi.stubGlobal("MediaRecorder", FakeRecorder);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => tracks }) },
    });
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:take", revokeObjectURL: () => {} }));
    const takes: (VerificationTake | null)[] = [];
    render(<VerificationRecorder loadPhrase={() => Promise.resolve(phrase("river copper lantern"))} value={null} onChange={(t) => takes.push(t)} />);
    await screen.findByText("river copper lantern");
    const now = Date.now();
    const spy = vi.spyOn(Date, "now").mockReturnValue(now);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /record the phrase/i }));
    });
    spy.mockReturnValue(now + 3000);
    fireEvent.click(await screen.findByRole("button", { name: /stop/i }));
    await waitFor(() => expect(takes.at(-1)?.token).toBe("tok-river copper lantern"));
    expect(takes.at(-1)?.file.type).toBe("audio/webm");
    expect(tracks[0]!.stop).toHaveBeenCalled();
    spy.mockRestore();
  });

  it("refuses a take that is too short", async () => {
    vi.stubGlobal("MediaRecorder", FakeRecorder);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: () => {} }] }) },
    });
    const onChange = vi.fn();
    render(<VerificationRecorder loadPhrase={() => Promise.resolve(phrase("river"))} value={null} onChange={onChange} />);
    await screen.findByText("river");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /record the phrase/i }));
    });
    fireEvent.click(await screen.findByRole("button", { name: /stop/i }));
    await screen.findByText("That recording was too short. Read the whole phrase.");
    expect(onChange.mock.calls.every(([t]) => t === null)).toBe(true);
  });
});
