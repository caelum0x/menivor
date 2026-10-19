import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { hasEmoji, mockApi } from "@/src/features/ai-actors/test-fetch";
import { TranslateWorkspace, VOICE_RULE } from "./TranslateWorkspace";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));

const OPTIONS = {
  languages: [{ code: "de", label: "German" }, { code: "tr", label: "Turkish" }],
  engines: [{ id: "kling", label: "Kling lip-sync", configured: true }, { id: "infinitetalk", label: "InfiniteTalk (RunPod)", configured: false }],
  videos: [{ id: "v1", title: "Our UGC ad", url: "https://cdn.test/own.mp4" }],
  voices: [{ actor_id: "a1", name: "Lena Varo", ready: true }, { actor_id: "a2", name: "Pell Ostrava", ready: false }],
  rules: [],
};
const PLANNED = {
  id: "r9", kind: "lipsync_translation", status: "planned", title: "Translate to German, Turkish", quote_usd: 1.37, credits: 411,
  approval_item_id: null, result: {}, error: "", created_at: null,
  plan: { steps: ["transcript", "translate (Relay)", "designed-voice TTS", "lip-sync (kling)", "burned captions"], usd_per_language: 0.685,
    targets: [{ code: "de", label: "German" }, { code: "tr", label: "Turkish" }] },
};

afterEach(() => vi.unstubAllGlobals());

describe("Lip-sync translate", () => {
  it("disables voices without a designed voice and states the rule", async () => {
    mockApi({ "GET /translate/options": OPTIONS, "GET /studio-renders": { renders: [] } });
    const { container } = render(<TranslateWorkspace />);
    const option = await screen.findByRole("option", { name: "Pell Ostrava (design a voice first)" });
    expect(option).toBeDisabled();
    expect(screen.getAllByText(VOICE_RULE).length).toBeGreaterThan(0);
    expect(hasEmoji(container.textContent ?? "")).toBe(false);
  });

  it("prices, shows the total and submits for approval", async () => {
    const calls = mockApi({
      "GET /translate/options": OPTIONS,
      "GET /studio-renders": { renders: [] },
      "POST /translate/plan": { render: PLANNED },
      "POST /studio-renders/r9/submit": { render: { ...PLANNED, status: "pending_approval" } },
    });
    render(<TranslateWorkspace />);
    await screen.findByRole("option", { name: "Our UGC ad" });
    fireEvent.change(screen.getByLabelText("Video"), { target: { value: "https://cdn.test/own.mp4" } });
    fireEvent.change(screen.getByLabelText("Voice"), { target: { value: "a1" } });
    fireEvent.click(screen.getByRole("button", { name: "German" }));
    fireEvent.click(screen.getByRole("button", { name: "Turkish" }));
    fireEvent.click(screen.getByRole("button", { name: "Price it" }));
    expect(await screen.findByTestId("translate-total")).toHaveTextContent("Total $1.37 (411 AI-video credits)");
    expect(calls.find((c) => c.key === "POST /translate/plan")?.body).toMatchObject({ targets: ["de", "tr"], actor_id: "a1" });
    fireEvent.click(screen.getByRole("button", { name: "Send for approval" }));
    await waitFor(() => expect(calls.map((c) => c.key)).toContain("POST /studio-renders/r9/submit"));
    expect(await screen.findByText(/Waiting for approval/)).toBeInTheDocument();
  });
});
