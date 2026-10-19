import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { hasEmoji, mockApi } from "@/src/features/ai-actors/test-fetch";
import { McpConnector } from "./McpConnector";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));

const INFO = {
  url: "https://api.menivor.test/api/v1/mcp",
  tools: [{ name: "brand_memory_get", description: "Read the brand memory.", annotations: { readOnlyHint: true } }],
  protocol_versions: ["2025-06-18"],
  claude_code: "claude mcp add --transport http menivor https://api.menivor.test/api/v1/mcp",
  json_config: { mcpServers: {} },
  rules: ["Spending tools only create approvals; a person approves in Menivor."],
};
const ROW = { id: "t1", name: "Claude", prefix: "mnv_mcp_abcd", workspace_id: null, scopes: ["read", "write"],
  expires_at: "2027-01-04T00:00:00Z", revoked: false, last_used_at: null, created_at: "2026-10-06T00:00:00Z" };

afterEach(() => vi.unstubAllGlobals());

describe("MCP connector", () => {
  it("shows the token once, then only the prefix", async () => {
    let tokens: unknown[] = [];
    mockApi({
      "GET /mcp/connector": INFO,
      "GET /mcp/tokens": () => ({ body: { tokens } }),
      "POST /mcp/tokens": () => {
        tokens = [ROW];
        return { body: { token: { ...ROW, token: "mnv_mcp_abcdSECRET" } } };
      },
    });
    const { container } = render(<McpConnector />);
    await screen.findByText(INFO.url);
    fireEvent.click(screen.getByRole("button", { name: "Create token" }));
    expect(await screen.findByTestId("fresh-token")).toHaveTextContent("mnv_mcp_abcdSECRET");
    expect(screen.getByText(/You will not see it again/)).toBeInTheDocument();
    await screen.findByText("mnv_mcp_abcd...");
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByText("mnv_mcp_abcdSECRET")).toBeNull();
    expect(hasEmoji(container.textContent ?? "")).toBe(false);
  });

  it("revoke calls DELETE", async () => {
    const calls = mockApi({
      "GET /mcp/connector": INFO,
      "GET /mcp/tokens": { tokens: [ROW] },
      "DELETE /mcp/tokens/t1": { token: { ...ROW, revoked: true } },
    });
    render(<McpConnector />);
    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(calls.map((c) => c.key)).toContain("DELETE /mcp/tokens/t1"));
  });
});
