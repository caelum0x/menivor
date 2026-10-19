import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type { WorkflowGraph } from "./api";
import { fromFlow, precheck, toFlow } from "./graph";
import { WorkflowCanvas } from "./WorkflowCanvas";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: async () => "test-token" }),
}));

beforeAll(() => {
  // React Flow measures nodes; jsdom has no layout APIs.
  class RO {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal("ResizeObserver", RO);
  if (!("DOMMatrixReadOnly" in window)) {
    class M {
      m22 = 1;
      constructor() {}
    }
    vi.stubGlobal("DOMMatrixReadOnly", M);
  }
});

afterEach(() => {
  vi.restoreAllMocks();
});

const CHAIN = ["brief", "script", "images", "video", "captions", "approve", "publish"] as const;
const STARTER: WorkflowGraph = {
  nodes: CHAIN.map((t, i) => ({ id: `n${i + 1}`, type: t, position: { x: i * 220, y: 120 }, data: {} })),
  edges: CHAIN.slice(1).map((_, i) => ({ id: `n${i + 1}->n${i + 2}`, source: `n${i + 1}`, target: `n${i + 2}` })),
};

const WORKFLOW = {
  id: "wf1",
  name: "Weekly UGC",
  space_id: "sp1",
  graph: STARTER,
  schedule: { enabled: false, weekday: null, hour: 9, label: "Runs every day at 09:00 UTC", next_run_at: null, last_run_at: null },
  updated_at: null,
};

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

function routeFetch(routes: Record<string, (init: RequestInit) => Response>) {
  const mock = vi.fn(async (url: string, init: RequestInit) => {
    const pathname = new URL(String(url)).pathname.replace("/api/v1", "");
    const key = `${init.method ?? "GET"} ${pathname}`;
    const handler = routes[key];
    if (!handler) throw new Error(`unexpected ${key}`);
    return handler(init);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

const baseRoutes = {
  "GET /workflows": () => jsonResponse({ status: 200, data: { workflows: [WORKFLOW], node_types: [], starter: STARTER } }),
  "GET /workflows/wf1": () => jsonResponse({ status: 200, data: { workflow: WORKFLOW, runs: [] } }),
};

describe("graph helpers", () => {
  it("round-trips the API graph through React Flow", () => {
    const flow = toFlow(STARTER);
    expect(flow.nodes[2]!.data).toMatchObject({ kind: "images", count: 1 });
    const back = fromFlow(flow.nodes, flow.edges);
    expect(back.nodes.map((n) => n.type)).toEqual([...CHAIN]);
    expect(back.edges).toEqual(STARTER.edges.map(({ source, target }) => ({ source, target })));
    expect(back.nodes[6]!.data).toEqual({ platforms: ["tiktok"] });
  });

  it("flags the same rules as the API", () => {
    expect(precheck(STARTER)).toBe("");
    const noApprove: WorkflowGraph = {
      nodes: [
        { id: "a", type: "brief", position: { x: 0, y: 0 }, data: {} },
        { id: "b", type: "video", position: { x: 0, y: 0 }, data: {} },
        { id: "c", type: "publish", position: { x: 0, y: 0 }, data: {} },
      ],
      edges: [
        { source: "a", target: "b" },
        { source: "b", target: "c" },
      ],
    };
    expect(precheck(noApprove)).toBe("Publish needs an Approve before it.");
    expect(precheck({ nodes: [], edges: [] })).toBe("Add a Brief to start the workflow.");
    const loop: WorkflowGraph = {
      nodes: [
        { id: "a", type: "brief", position: { x: 0, y: 0 }, data: {} },
        { id: "b", type: "script", position: { x: 0, y: 0 }, data: {} },
        { id: "c", type: "approve", position: { x: 0, y: 0 }, data: {} },
      ],
      edges: [
        { source: "a", target: "b" },
        { source: "b", target: "c" },
        { source: "c", target: "b" },
      ],
    };
    expect(precheck(loop)).toContain("loops");
    const captions: WorkflowGraph = {
      nodes: [
        { id: "a", type: "brief", position: { x: 0, y: 0 }, data: {} },
        { id: "b", type: "images", position: { x: 0, y: 0 }, data: {} },
        { id: "c", type: "captions", position: { x: 0, y: 0 }, data: {} },
      ],
      edges: [
        { source: "a", target: "b" },
        { source: "b", target: "c" },
      ],
    };
    expect(precheck(captions)).toBe("Captions go after a Video.");
  });
});

describe("workflow canvas", () => {
  it("renders the starter chain from the API", async () => {
    routeFetch(baseRoutes);
    render(<WorkflowCanvas />);
    await waitFor(() => expect(screen.getByDisplayValue("Weekly UGC")).toBeInTheDocument());
    for (const kind of CHAIN) {
      await waitFor(() => expect(screen.getByTestId(`node-${kind}`)).toBeInTheDocument());
    }
    expect(screen.getByText("Nothing after this runs until you approve.")).toBeInTheDocument();
    expect(screen.getAllByText("credits")).toHaveLength(2);
  });

  it("shows the API's 422 message when Save is refused", async () => {
    routeFetch({
      ...baseRoutes,
      "PUT /workflows/wf1": () =>
        jsonResponse({ status: 422, message: "0123456789abcdef0123: Publish needs an Approve before it." }, 422),
    });
    render(<WorkflowCanvas />);
    await waitFor(() => expect(screen.getByTestId("node-brief")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Save$/ }));
    await waitFor(() => expect(screen.getByText("Publish needs an Approve before it.")).toBeInTheDocument());
  });

  it("Run now saves, runs and lists the steps", async () => {
    const run = {
      id: "r1",
      workflow_id: "wf1",
      trigger: "manual",
      status: "waiting_for_approval",
      error: "",
      created_at: null,
      steps: [
        { node_id: "n1", type: "brief", label: "Brief", status: "done" },
        { node_id: "n3", type: "images", label: "Images", status: "pending_approval", action_id: "a1", credits: 1 },
        { node_id: "n7", type: "publish", label: "Publish", status: "after_approval" },
      ],
    };
    const mock = routeFetch({
      ...baseRoutes,
      "PUT /workflows/wf1": () => jsonResponse({ status: 200, data: { workflow: WORKFLOW } }),
      "POST /workflows/wf1/run": () => jsonResponse({ status: 200, data: { run } }),
    });
    render(<WorkflowCanvas />);
    await waitFor(() => expect(screen.getByTestId("node-brief")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Run now/ }));
    const panel = await screen.findByTestId("run-panel");
    expect(panel).toHaveTextContent("Waiting for your approval (1 credits)");
    expect(panel).toHaveTextContent("Runs after approval");
    expect(screen.getByRole("link", { name: "Approve in the Agent queue" })).toHaveAttribute("href", "/agent");
    const keys = mock.mock.calls.map(([u, i]) => `${(i as RequestInit).method ?? "GET"} ${new URL(String(u)).pathname}`);
    expect(keys).toContain("PUT /api/v1/workflows/wf1");
    expect(keys).toContain("POST /api/v1/workflows/wf1/run");
  });
});

describe("copy rules", () => {
  it("uses no emoji and no 'indie' wording", () => {
    const dir = __dirname;
    const files = [
      ...readdirSync(dir).filter((f) => f.endsWith(".tsx") && !f.endsWith(".test.tsx")),
      "graph.ts",
      "api.ts",
    ];
    const pagePath = path.resolve(dir, "../../../app/workflows/page.tsx");
    for (const text of [...files.map((f) => readFileSync(path.join(dir, f), "utf8")), readFileSync(pagePath, "utf8")]) {
      expect(text).not.toMatch(/\p{Extended_Pictographic}/u);
      expect(text.toLowerCase()).not.toContain("indie");
    }
  });
});
