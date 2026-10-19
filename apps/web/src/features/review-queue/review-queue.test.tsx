import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { ReviewQueue } from "./ReviewQueue";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));

const EMOJI = /\p{Extended_Pictographic}/u;

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: "OK",
    text: async () => JSON.stringify(body),
    json: async () => body,
    headers: { get: () => null },
  } as unknown as Response;
}

const ITEM = (id: string, kind = "image") => ({
  id,
  source: "creative_review",
  external_ref: `lib-${id}`,
  title: `Creative ${id}`,
  summary: "",
  status: "pending",
  payload: { kind, media_url: `https://cdn.test/${id}.png`, regenerate_credits: kind === "video" ? 5 : 1 },
});

const QUEUE = {
  items: [ITEM("a1"), ITEM("a2", "video")],
  pending: 2,
  reasons: {
    approve: [
      { id: "on_brand", label: "On brand" },
      { id: "strong_hook", label: "Strong hook" },
      { id: "ready_to_post", label: "Ready to post" },
    ],
    fix: [
      { id: "off_brand", label: "Off brand" },
      { id: "weak_hook", label: "Weak hook" },
    ],
  },
  stats: { by_status: { approved: 4 }, top_reasons: [{ id: "on_brand", label: "On brand", count: 3 }] },
};

const DECIDED = { item: ITEM("a1"), idempotent: false, review: { status: "approved", reason: "on_brand", reason_label: "On brand" }, regenerate_action: null };

beforeAll(() => {
  if (!("PointerEvent" in window)) {
    class PE extends MouseEvent {}
    // @ts-expect-error jsdom has no PointerEvent
    window.PointerEvent = PE;
  }
});

afterEach(() => vi.unstubAllGlobals());

function setup() {
  const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({ status: 200, data: QUEUE }));
  fetchMock.mockResolvedValue(jsonResponse({ status: 200, data: DECIDED }));
  vi.stubGlobal("fetch", fetchMock);
  render(<ReviewQueue />);
  return fetchMock;
}

function decideBody(fetchMock: ReturnType<typeof vi.fn>) {
  const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/decide"));
  return call ? { url: String(call[0]), body: JSON.parse(call[1].body as string) } : null;
}

describe("review queue", () => {
  it("shows progress, stats and no emoji", async () => {
    setup();
    expect(await screen.findByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByText(/On brand \(3\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Regenerate for 1 credits/ })).toBeInTheDocument();
    expect(EMOJI.test(document.body.textContent ?? "")).toBe(false);
  });

  it("keyboard: 1 picks a chip, Right approves with it", async () => {
    const fetchMock = setup();
    await screen.findByText("1 of 2");
    fireEvent.keyDown(window, { key: "1" });
    expect(screen.getByRole("button", { name: /On brand/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() => expect(decideBody(fetchMock)).not.toBeNull());
    const sent = decideBody(fetchMock)!;
    expect(sent.url).toContain("/review/a1/decide");
    expect(sent.body).toMatchObject({ decision: "approve", reason: "on_brand" });
    expect(await screen.findByText("2 of 2")).toBeInTheDocument();
  });

  it("regenerate without a chip is blocked; with a chip it confirms the spend", async () => {
    const fetchMock = setup();
    await screen.findByText("1 of 2");
    fireEvent.keyDown(window, { key: "r" });
    expect(await screen.findByText(/Pick what to change first/)).toBeInTheDocument();
    expect(decideBody(fetchMock)).toBeNull();
    fireEvent.keyDown(window, { key: "2" });
    fireEvent.keyDown(window, { key: "r" });
    await waitFor(() => expect(decideBody(fetchMock)).not.toBeNull());
    expect(decideBody(fetchMock)!.body).toMatchObject({ decision: "regenerate", reason: "weak_hook", confirm_spend: true });
  });

  it("ignores shortcuts while typing", async () => {
    const fetchMock = setup();
    await screen.findByText("1 of 2");
    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: "a" });
    expect(decideBody(fetchMock)).toBeNull();
  });

  it("swipe right past the threshold approves", async () => {
    const fetchMock = setup();
    const card = await screen.findByTestId("review-card");
    act(() => {
      fireEvent.pointerDown(card, { clientX: 10 });
      fireEvent.pointerMove(card, { clientX: 160 });
      fireEvent.pointerUp(card, { clientX: 160 });
    });
    await waitFor(() => expect(decideBody(fetchMock)).not.toBeNull());
    expect(decideBody(fetchMock)!.body.decision).toBe("approve");
  });

  it("empty queue links to the agent", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ status: 200, data: { ...QUEUE, items: [], pending: 0 } })));
    render(<ReviewQueue />);
    expect(await screen.findByText("Nothing to review")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Agent" })).toHaveAttribute("href", "/agent");
  });
});
