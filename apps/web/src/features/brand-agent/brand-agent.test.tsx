import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { decideAction, saveMemorySection, sendChip, streamTurn, type AgentMessage } from "./api";
import { ChatView } from "./ChatView";
import { MessageCard } from "./MessageCard";
import { createSseParser } from "./sse";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: async () => "test-token" }),
}));

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: status < 400 ? "OK" : "Error",
    text: async () => JSON.stringify(body),
    json: async () => body,
    headers: { get: () => null },
  } as unknown as Response;
}

function sseResponse(frames: string[]): Response {
  const encoder = new TextEncoder();
  const chunks = frames.map((f) => encoder.encode(f));
  let i = 0;
  return {
    ok: true,
    status: 200,
    headers: { get: () => "text/event-stream" },
    body: {
      getReader: () => ({
        read: async () => (i < chunks.length ? { value: chunks[i++], done: false } : { value: undefined, done: true }),
      }),
    },
  } as unknown as Response;
}

const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

const POSITIONING: AgentMessage = {
  id: "m2",
  seq: 2,
  role: "assistant",
  content: "Here is how I read your positioning. Is this right?",
  card: {
    type: "setup_step",
    step: "positioning",
    title: "Positioning",
    index: 1,
    total: 4,
    data: {
      category: "Developer tools: backend platform",
      one_liner: "Supabase + Neon in one",
      pricing_hook: "$25 a project, flat",
      colors: ["#3d3f9e"],
      fonts: ["Instrument Sans"],
      logo_url: "",
    },
  },
  chips: [
    { label: "Yes, save it", choice: "yes", step: "positioning" },
    { label: "No, change it", choice: "no", step: "positioning" },
  ],
  action_id: null,
  action: null,
  created_at: null,
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("sse parser", () => {
  it("joins split frames and parses JSON data", () => {
    const parser = createSseParser();
    expect(parser.push('event: delta\ndata: {"text":"He')).toEqual([]);
    const events = parser.push('llo"}\n\nevent: done\ndata: {}\n\n');
    expect(events).toEqual([
      { event: "delta", data: { text: "Hello" } },
      { event: "done", data: {} },
    ]);
  });
});

describe("brand agent api", () => {
  it("posts chips, approvals and Brain edits to the agent routes", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 200, data: { messages: [] } }));
    await sendChip("s1", { choice: "yes", step: "positioning" }, { token: "t" });
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 200, data: { action: { id: "a1", status: "executed" } } }));
    const action = await decideAction("a1", "approve", { token: "t" });
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 200, data: { version: 5 } }));
    await saveMemorySection("sp1", "positioning", { one_liner: "x" }, { token: "t" });

    const calls = fetchMock.mock.calls.map(([url, init]) => [String(url), init.method]);
    expect(calls[0]).toEqual([expect.stringContaining("/agent/sessions/s1/chips"), "POST"]);
    expect(calls[1]).toEqual([expect.stringContaining("/agent/actions/a1/approve"), "POST"]);
    expect(calls[2]).toEqual([expect.stringContaining("/agent/spaces/sp1/memory/positioning"), "PUT"]);
    expect(action.status).toBe("executed");
  });

  it("streams deltas and full messages", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      sseResponse([
        frame("start", { session_id: "s1" }),
        frame("delta", { message_id: "m2", text: "Here is " }),
        frame("message", POSITIONING),
        frame("done", { count: 1 }),
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);
    const deltas: string[] = [];
    const out = await streamTurn("s1", { text: "hi" }, { onDelta: (_id, t) => deltas.push(t) }, { token: "t" });
    expect(deltas).toEqual(["Here is "]);
    expect(out.map((m) => m.id)).toEqual(["m2"]);
    const [, init] = fetchMock.mock.calls[0]!;
    expect(init.headers["x-api-key"]).toBe("t");
  });

  it("authenticates the stream like every other call when there is no signed-in token", async () => {
    window.localStorage.setItem("menivor.device.api_key", "device-key-1");
    try {
      const fetchMock = vi.fn().mockResolvedValueOnce(sseResponse([frame("done", { count: 0 })]));
      vi.stubGlobal("fetch", fetchMock);
      await streamTurn("s1", { text: "hi" });
      const [, init] = fetchMock.mock.calls[0]!;
      expect(init.headers["x-api-key"]).toBe("device-key-1");
    } finally {
      window.localStorage.removeItem("menivor.device.api_key");
    }
  });
});

describe("chat view", () => {
  it("shows the setup step card and sends the chip through the stream", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ status: 200, data: { session: { id: "s1" }, messages: [POSITIONING], setup: { step: "positioning" } } }),
    );
    render(<ChatView sessionId="s1" />);
    expect(await screen.findByText("Supabase + Neon in one")).toBeInTheDocument();
    expect(screen.getByText("#3d3f9e")).toBeInTheDocument();

    fetchMock.mockResolvedValueOnce(
      sseResponse([
        frame("message", { ...POSITIONING, id: "m3", content: "Saved Positioning to brand memory (version 1).", card: null, chips: [] }),
        frame("done", { count: 1 }),
      ]),
    );
    fireEvent.click(screen.getByRole("button", { name: "Yes, save it" }));
    expect(await screen.findByText("Saved Positioning to brand memory (version 1).")).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[1]!;
    expect(String(url)).toContain("/agent/sessions/s1/stream");
    expect(JSON.parse(init.body)).toMatchObject({ choice: "yes", step: "positioning" });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Yes, save it" })).not.toBeInTheDocument());
  });

  it("shows a blocked action's missing step with links and a product picker, not Approve", async () => {
    const blocked = {
      id: "m9",
      role: "assistant",
      content: "I'll rebuild that ad for your brand with Ad Clone. First: Which product is this ad for?",
      chips: [
        { label: "Use Linen Overshirt", choice: "use_product", action_id: "a1", value: "catalog:p1" },
        { label: "Get credits", choice: "open", href: "/billing" },
      ],
      card: { type: "action", data: {} },
      action: {
        id: "a1", kind: "clone_ad", status: "blocked", title: "Clone ad", credits_estimate: 0,
        spends_credits: true, publishes: false, error: "", result: null, created_at: null,
        needs: [{ id: "product", title: "Which product is this ad for?", detail: "Pick the product.", options: [] }],
      },
      created_at: null,
    };
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({ status: 200, data: { session: { id: "s1" }, messages: [blocked], setup: { step: null } } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<ChatView sessionId="s1" />);
    expect(await screen.findByText("needs one step")).toBeInTheDocument();
    expect(screen.getByText("Pick the product.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Get credits" })).toHaveAttribute("href", "/billing");
    fetchMock.mockResolvedValueOnce(sseResponse([frame("done", { count: 0 })]));
    fireEvent.click(screen.getByRole("button", { name: "Use Linen Overshirt" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetchMock.mock.calls[1]![1].body)).toMatchObject({
      choice: "use_product", action_id: "a1", value: "catalog:p1",
    });
  });

  it("shows the catalog as a one-click product picker with thumbnails, 6 at a time, searchable", async () => {
    const options = Array.from({ length: 8 }, (_, i) => ({
      id: `catalog:p${i}`, name: `Product ${i}`, detail: "", thumbnail_url: `https://cdn.example.com/${i}.jpg`,
    }));
    const blocked = {
      id: "m9", role: "assistant", content: "First: Which product is this ad for?",
      chips: options.slice(0, 6).map((o) => ({ label: `Use ${o.name}`, choice: "use_product", action_id: "a1", value: o.id })),
      card: { type: "action", data: {} },
      action: {
        id: "a1", kind: "clone_ad", status: "blocked", title: "Clone ad", credits_estimate: 0, spends_credits: true,
        publishes: false, error: "", result: null, created_at: null,
        needs: [{ id: "product", title: "Which product is this ad for?", detail: "", options }],
      },
      created_at: null,
    };
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({ status: 200, data: { session: { id: "s1" }, messages: [blocked], setup: { step: null } } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<ChatView sessionId="s1" />);
    const picker = await screen.findByRole("group", { name: "Pick a product" });
    expect(picker.querySelectorAll("button")).toHaveLength(6);
    expect(container.querySelectorAll('img[src^="https://cdn.example.com/"]')).toHaveLength(6);
    expect(screen.queryByRole("button", { name: "Use Product 0" })).not.toBeInTheDocument(); // no duplicate chips
    fireEvent.change(screen.getByPlaceholderText("Search 8 products"), { target: { value: "product 7" } });
    expect(picker.querySelectorAll("button")).toHaveLength(1);
    fetchMock.mockResolvedValueOnce(sseResponse([frame("done", { count: 0 })]));
    fireEvent.click(screen.getByRole("button", { name: /Product 7/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetchMock.mock.calls[1]![1].body)).toMatchObject({
      choice: "use_product", action_id: "a1", value: "catalog:p7",
    });
  });

  it("has exactly one primary action (Send)", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({ status: 200, data: { session: { id: "s1" }, messages: [], setup: { step: null } } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<ChatView sessionId="s1" />);
    expect(await screen.findByText("Set up your brand")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });
});

describe("message card", () => {
  it("labels competitors the site names as where switchers come from", () => {
    render(
      <MessageCard
        card={{
          type: "setup_step",
          step: "market",
          data: {
            competitors: [{ name: "Supabase", relationship: "switch_source", note: "" }],
            insights: ["Compare only on facts both sites publish."],
          },
        }}
        action={null}
      />,
    );
    expect(screen.getByText("Where switchers come from")).toBeInTheDocument();
  });
});

describe("copy rules for the agent UI", () => {
  const dir = path.dirname(new URL(import.meta.url).pathname);
  const sources = readdirSync(dir)
    .filter((f) => /\.(tsx?|ts)$/.test(f) && !f.endsWith(".test.tsx"))
    .map((f) => readFileSync(path.join(dir, f), "utf8"));

  it("never uses the word indie for audiences", () => {
    for (const src of sources) expect(src).not.toMatch(/\bindie/i);
  });

  it("uses icons, not emoji glyphs", () => {
    const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u;
    for (const src of sources) expect(src).not.toMatch(emoji);
  });
});
