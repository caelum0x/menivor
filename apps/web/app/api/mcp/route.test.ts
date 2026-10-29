import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import nextConfig from "../../../next.config.mjs";
import { PUBLISHING_TOOLS_UNAVAILABLE, publishingToolsEnabled } from "@/lib/mcp/tools";
import { POST } from "./route";

const LIVE_TOOLS = [
  "create_reel",
  "get_job",
  "ad_from_url",
  "get_performance",
  "generation_quote",
  "wallet_balance",
  "list_media_models",
];

function rpc(body: unknown, headers: Record<string, string> = {}): NextRequest {
  return new NextRequest("https://menivor.com/api/mcp", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("publishing tools flag", () => {
  it("defaults off and accepts only an explicit on-switch", () => {
    expect(publishingToolsEnabled(undefined)).toBe(false);
    expect(publishingToolsEnabled("")).toBe(false);
    expect(publishingToolsEnabled("0")).toBe(false);
    expect(publishingToolsEnabled("false")).toBe(false);
    expect(publishingToolsEnabled("off")).toBe(false);
    expect(publishingToolsEnabled("1")).toBe(true);
    expect(publishingToolsEnabled("true")).toBe(true);
    expect(publishingToolsEnabled(" YES ")).toBe(true);
    expect(publishingToolsEnabled("on")).toBe(true);
  });
});

describe("POST /api/mcp", () => {
  it("initializes with a supported protocol version", async () => {
    const res = await POST(
      rpc({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-03-26" } }),
    );
    const body = await res.json();
    expect(res.status).toBe(200);
    expect(body.result.protocolVersion).toBe("2025-03-26");
    expect(body.result.serverInfo.name).toBe("menivor");
    expect(body.result.capabilities.tools).toBeDefined();
  });

  it("lists tools without a key and hides posting tools while publishing is closed", async () => {
    const res = await POST(rpc({ jsonrpc: "2.0", id: 2, method: "tools/list" }));
    const body = await res.json();
    const names = body.result.tools.map((tool: { name: string }) => tool.name);
    expect(names).toEqual(LIVE_TOOLS);
    expect(names).not.toContain("schedule_publish");
    expect(names).not.toContain("list_scheduled");
  });

  it("rejects schedule_publish and list_scheduled without calling the API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    for (const name of ["schedule_publish", "list_scheduled"] as const) {
      const res = await POST(
        rpc(
          { jsonrpc: "2.0", id: 8, method: "tools/call", params: { name, arguments: {} } },
          { authorization: "Bearer mk_test_123" },
        ),
      );
      const body = await res.json();
      expect(res.status).toBe(200);
      expect(body.result.isError).toBe(true);
      expect(body.result.content[0].text).toBe(PUBLISHING_TOOLS_UNAVAILABLE);
      expect(body.result.content[0].text).toMatch(/not available yet/i);
    }
    const unsigned = await POST(
      rpc({
        jsonrpc: "2.0",
        id: 9,
        method: "tools/call",
        params: { name: "schedule_publish", arguments: { job_id: "job_1", platforms: ["tiktok"], scheduled_at: "2099-01-01T00:00:00Z" } },
      }),
    );
    const unsignedBody = await unsigned.json();
    expect(unsigned.status).toBe(200);
    expect(unsignedBody.result.isError).toBe(true);
    expect(unsignedBody.result.content[0].text).toMatch(/not available yet/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("lists and forwards schedule_publish only when MENIVOR_MCP_PUBLISHING_TOOLS is on", async () => {
    vi.stubEnv("MENIVOR_MCP_PUBLISHING_TOOLS", "1");
    const listed = await POST(rpc({ jsonrpc: "2.0", id: 10, method: "tools/list" }));
    const names = (await listed.json()).result.tools.map((tool: { name: string }) => tool.name);
    expect(names).toEqual([
      "create_reel",
      "get_job",
      "ad_from_url",
      "schedule_publish",
      "list_scheduled",
      ...LIVE_TOOLS.slice(3),
    ]);

    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ status: 200, data: { id: "sch_1", status: "pending" } }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const res = await POST(
      rpc(
        {
          jsonrpc: "2.0",
          id: 11,
          method: "tools/call",
          params: {
            name: "schedule_publish",
            arguments: { job_id: "job_1", platforms: ["tiktok"], scheduled_at: "2099-01-01T00:00:00Z" },
          },
        },
        { authorization: "Bearer mk_test_123" },
      ),
    );
    const body = await res.json();
    expect(body.result.isError).toBe(false);
    expect(body.result.structuredContent).toEqual({ id: "sch_1", status: "pending" });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/jobs\/job_1\/schedule$/);
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["x-api-key"]).toBe("mk_test_123");
  });

  it("acknowledges notifications with 202", async () => {
    const res = await POST(rpc({ jsonrpc: "2.0", method: "notifications/initialized" }));
    expect(res.status).toBe(202);
  });

  it("refuses tools/call without a key", async () => {
    const res = await POST(
      rpc({ jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "wallet_balance", arguments: {} } }),
    );
    expect(res.status).toBe(401);
    expect(res.headers.get("WWW-Authenticate")).toContain("Bearer");
    expect((await res.json()).error.code).toBe(-32001);
  });

  it("forwards the bearer key to the REST API and returns structured content", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ status: 200, data: { available_micros: 5_000_000 } }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const res = await POST(
      rpc(
        { jsonrpc: "2.0", id: 4, method: "tools/call", params: { name: "wallet_balance", arguments: {} } },
        { authorization: "Bearer mk_test_123" },
      ),
    );
    const body = await res.json();
    expect(body.result.isError).toBe(false);
    expect(body.result.structuredContent).toEqual({ available_micros: 5_000_000 });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/wallet$/);
    expect((init.headers as Record<string, string>)["x-api-key"]).toBe("mk_test_123");
  });

  it("reports invalid arguments as a tool error without calling upstream", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await POST(
      rpc(
        { jsonrpc: "2.0", id: 5, method: "tools/call", params: { name: "get_job", arguments: { job_id: "../x" } } },
        { "x-api-key": "k" },
      ),
    );
    const body = await res.json();
    expect(body.result.isError).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("redirects /docs to /mcp", async () => {
    const redirects = await nextConfig.redirects();
    expect(redirects).toContainEqual({ source: "/docs", destination: "/mcp", permanent: true });
  });

  it("rejects unknown methods and malformed JSON", async () => {
    const unknown = await (await POST(rpc({ jsonrpc: "2.0", id: 6, method: "resources/list" }))).json();
    expect(unknown.error.code).toBe(-32601);
    const bad = await POST(
      new NextRequest("https://menivor.com/api/mcp", { method: "POST", body: "{not json" }),
    );
    expect(bad.status).toBe(400);
  });
});
