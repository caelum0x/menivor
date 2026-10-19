/** Hosted MCP connector client: endpoint info and connector tokens. */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import { apiPath } from "@/src/shared/api/path";

export interface McpTool {
  name: string;
  description: string;
  annotations?: { readOnlyHint?: boolean };
}

export interface ConnectorInfo {
  url: string;
  tools: McpTool[];
  protocol_versions: string[];
  claude_code: string;
  json_config: Record<string, unknown>;
  rules: string[];
}

export interface McpToken {
  id: string;
  name: string;
  prefix: string;
  workspace_id: string | null;
  scopes: string[];
  expires_at: string | null;
  revoked: boolean;
  last_used_at: string | null;
  created_at: string | null;
  /** Only on the mint response, shown once. */
  token?: string;
}

export interface MintInput {
  name: string;
  scopes: string[];
  workspace_id?: string;
  ttl_days: number;
}

export function getConnector(options?: RequestOptions): Promise<ConnectorInfo> {
  return apiRequest<ConnectorInfo>("/mcp/connector", { options });
}

export async function listTokens(options?: RequestOptions): Promise<McpToken[]> {
  return (await apiRequest<{ tokens: McpToken[] }>("/mcp/tokens", { options })).tokens;
}

export async function mintToken(input: MintInput, options?: RequestOptions): Promise<McpToken> {
  const body = input.workspace_id ? input : { ...input, workspace_id: undefined };
  return (await apiRequest<{ token: McpToken }>("/mcp/tokens", { method: "POST", body, options })).token;
}

export async function revokeToken(id: string, options?: RequestOptions): Promise<McpToken> {
  return (await apiRequest<{ token: McpToken }>(apiPath`/mcp/tokens/${id}`, { method: "DELETE", options }))
    .token;
}
