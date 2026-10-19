import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

function rpc(body: unknown, headers: Record<string, string> = {}): NextRequest {
  return new NextRequest("https://menivor.com/api/mcp", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

afterEach(() => vi.unstubAllGlobals());

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

  it("lists tools without a key", async () => {
    const res = await POST(rpc({ jsonrpc: "2.0", id: 2, method: "tools/list" }));
    const body = await res.json();
    const names = body.result.tools.map((tool: { name: string }) => tool.name);
    expect(names).toEqual(
      expect.arrayContaining(["create_reel", "get_job", "ad_from_url", "schedule_publish", "wallet_balance"]),
    );
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

  it("rejects unknown methods and malformed JSON", async () => {
    const unknown = await (await POST(rpc({ jsonrpc: "2.0", id: 6, method: "resources/list" }))).json();
    expect(unknown.error.code).toBe(-32601);
    const bad = await POST(
      new NextRequest("https://menivor.com/api/mcp", { method: "POST", body: "{not json" }),
    );
    expect(bad.status).toBe(400);
  });
});
