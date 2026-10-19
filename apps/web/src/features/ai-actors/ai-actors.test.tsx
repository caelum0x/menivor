import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActorsWorkspace } from "./ActorsWorkspace";
import { ATTEST_TEXT } from "./CreateActorForm";
import { hasEmoji, mockApi } from "./test-fetch";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));

const ACTOR = {
  id: "a1", slug: "", name: "Lena Varo", persona: "Barista", look_prompt: "Original woman", voice_design_prompt: "Bright",
  product_shot_template: "Holds {product}", face_image_url: "https://cdn.test/f.png", voice_id: "", builtin: false,
  status: "ready", provenance: { synthetic: true, generator: "user-defined", face: "generated" },
  consent: { type: "synthetic_no_real_person", attested_by: "u1", attested_at: "2026-10-06" },
};
const LISTING = {
  presets: [{ ...ACTOR, id: "preset:mira-soltane", slug: "mira-soltane", name: "Mira Soltane", face_image_url: "", builtin: true }],
  mine: [ACTOR],
  rules: ["Original synthetic people only: no real person's face, name or voice."],
};

afterEach(() => vi.unstubAllGlobals());

function fill(label: RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("AI actors", () => {
  it("blocks create without the attestation and shows the likeness message", async () => {
    const calls = mockApi({
      "GET /actors": LISTING,
      "POST /actors": () => ({ status: 422, body: "name: names a real person (Taylor Swift); AI actors are original people only" }),
    });
    render(<ActorsWorkspace />);
    await screen.findByText("Mira Soltane");
    fill(/^Name$/, "Taylor Swift");
    fill(/^Look$/, "a woman");
    fill(/^Voice$/, "warm voice");
    const create = screen.getByRole("button", { name: "Create actor" });
    expect(create).toBeDisabled();
    fireEvent.click(screen.getByLabelText(ATTEST_TEXT));
    expect(create).not.toBeDisabled();
    fireEvent.click(create);
    expect(await screen.findByRole("alert")).toHaveTextContent("names a real person");
    expect(calls.find((c) => c.key === "POST /actors")?.body).toMatchObject({ attest_synthetic: true });
  });

  it("prices a product shot then sends it for approval", async () => {
    const planned = { id: "r1", kind: "actor_shot", status: "planned", title: "Lena Varo holding Brewly", plan: {},
      quote_usd: 0.42, credits: 126, approval_item_id: null, result: {}, error: "", created_at: null };
    const calls = mockApi({
      "GET /actors": LISTING,
      "POST /actors/a1/shots/plan": { render: planned },
      "POST /studio-renders/r1/submit": { render: { ...planned, status: "pending_approval", approval_item_id: "i1" } },
    });
    render(<ActorsWorkspace />);
    fireEvent.click(await screen.findByRole("button", { name: /Lena Varo/ }));
    expect(screen.getByLabelText("Provenance")).toHaveTextContent("synthetic no real person");
    fireEvent.change(screen.getByLabelText("Product"), { target: { value: "Brewly" } });
    fireEvent.click(screen.getByRole("button", { name: "Price the shot" }));
    expect(await screen.findByText(/126 AI-video credits/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send for approval" }));
    expect(await screen.findByText("Waiting for approval")).toBeInTheDocument();
    expect(calls.map((c) => c.key)).toContain("POST /studio-renders/r1/submit");
    expect(calls.find((c) => c.key === "POST /actors/a1/shots/plan")?.body).toMatchObject({ product: "Brewly", seconds: 5 });
  });

  it("queues a face for approval and never shows emoji", async () => {
    mockApi({ "GET /actors": LISTING, "POST /actors/a1/face": { action: { id: "x", status: "pending", title: "Face", credits_estimate: 1 } } });
    const { container } = render(<ActorsWorkspace />);
    fireEvent.click(await screen.findByRole("button", { name: /Lena Varo/ }));
    fireEvent.click(screen.getByRole("button", { name: "Make face" }));
    expect(await screen.findByText(/Face queued for approval \(1 credits\)/)).toBeInTheDocument();
    expect(hasEmoji(container.textContent ?? "")).toBe(false);
  });
});
