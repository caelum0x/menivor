import { NextResponse, type NextRequest } from "next/server";
import {
  PUBLISHING_TOOL_NAMES,
  PUBLISHING_TOOLS_UNAVAILABLE,
  SCHEDULER_TOOL_NAMES,
  SCHEDULER_TOOLS_UNAVAILABLE,
  ToolError,
  listTools,
  mcpPublishingToolsEnabled,
  mcpSchedulerToolsEnabled,
  runTool,
} from "@/lib/mcp/tools";

/**
 * Menivor remote MCP server (Streamable HTTP transport, stateless).
 *
 * `POST /api/mcp` accepts JSON-RPC 2.0 messages (single or batched) and
 * answers with `application/json`; no session id is issued and no SSE stream
 * is opened, which the Streamable HTTP spec allows for servers that only
 * answer requests. `initialize`, `ping` and `tools/list` are open so MCP
 * directories can inspect the server; `tools/call` requires the caller's
 * personal Menivor API key as `Authorization: Bearer <key>` (or `x-api-key`),
 * which is forwarded to the REST API and never stored here.
 */

const SERVER_INFO = { name: "menivor", title: "Menivor", version: "1.0.0" } as const;
const SUPPORTED_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"] as const;
const MAX_BODY_BYTES = 1_000_000;
const MAX_BATCH = 20;
const INSTRUCTIONS =
  "Menivor makes short-form vertical video. Use create_reel then poll get_job until the job completes; " +
  "use generation_quote or list_media_models to check prices first and wallet_balance to check funds. " +
  "Every call acts as the owner of the API key.";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers":
    "Authorization, Content-Type, x-api-key, Mcp-Protocol-Version, Mcp-Session-Id",
  "Access-Control-Expose-Headers": "WWW-Authenticate",
} as const;

type JsonRpcId = string | number | null;

interface JsonRpcRequest {
  readonly jsonrpc?: unknown;
  readonly id?: unknown;
  readonly method?: unknown;
  readonly params?: unknown;
}

interface JsonRpcResponse {
  readonly jsonrpc: "2.0";
  readonly id: JsonRpcId;
  readonly result?: unknown;
  readonly error?: { readonly code: number; readonly message: string };
}

const PARSE_ERROR = -32700;
const INVALID_REQUEST = -32600;
const METHOD_NOT_FOUND = -32601;
const INVALID_PARAMS = -32602;
const UNAUTHORIZED = -32001;

class RpcError extends Error {
  readonly code: number;
  constructor(code: number, message: string) {
    super(message);
    this.code = code;
  }
}

function json(body: unknown, status = 200, extra: Record<string, string> = {}): NextResponse {
  return NextResponse.json(body, { status, headers: { ...CORS_HEADERS, ...extra } });
}

/** The caller's personal API key, from a Bearer token or `x-api-key`. */
function apiKeyFrom(request: NextRequest): string | null {
  const bearer = request.headers.get("authorization")?.match(/^Bearer\s+(.+)$/i)?.[1]?.trim();
  const key = bearer || request.headers.get("x-api-key")?.trim();
  return key && key.length <= 512 ? key : null;
}

function negotiateVersion(params: unknown): string {
  const requested =
    params && typeof params === "object" && "protocolVersion" in params
      ? (params as { protocolVersion?: unknown }).protocolVersion
      : undefined;
  return typeof requested === "string" &&
    (SUPPORTED_VERSIONS as readonly string[]).includes(requested)
    ? requested
    : SUPPORTED_VERSIONS[0];
}

function toolResult(value: unknown, isError = false) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const structured =
    !isError && value !== null && typeof value === "object" && !Array.isArray(value)
      ? { structuredContent: value }
      : {};
  return { content: [{ type: "text", text }], ...structured, isError };
}

async function dispatch(
  message: JsonRpcRequest,
  apiKey: string | null,
  publishingTools: boolean,
  schedulerTools: boolean,
): Promise<unknown> {
  const params = message.params;
  switch (message.method) {
    case "initialize":
      return {
        protocolVersion: negotiateVersion(params),
        capabilities: { tools: { listChanged: false } },
        serverInfo: SERVER_INFO,
        instructions: INSTRUCTIONS,
      };
    case "ping":
      return {};
    case "tools/list":
      return { tools: listTools(publishingTools, schedulerTools) };
    case "tools/call": {
      if (!params || typeof params !== "object") {
        throw new RpcError(INVALID_PARAMS, "tools/call needs a name and arguments");
      }
      const { name, arguments: args } = params as { name?: unknown; arguments?: unknown };
      if (typeof name !== "string") throw new RpcError(INVALID_PARAMS, "tools/call needs a tool name");
      // Refuse before asking for a key: a key does not unlock posting while it is closed.
      if (!publishingTools && PUBLISHING_TOOL_NAMES.has(name)) {
        return toolResult(PUBLISHING_TOOLS_UNAVAILABLE, true);
      }
      if (!schedulerTools && SCHEDULER_TOOL_NAMES.has(name)) {
        return toolResult(SCHEDULER_TOOLS_UNAVAILABLE, true);
      }
      if (!apiKey) {
        throw new RpcError(
          UNAUTHORIZED,
          "Send your Menivor API key as 'Authorization: Bearer <key>'. Create one at https://menivor.com/account/api-keys",
        );
      }
      try {
        return toolResult(await runTool(name, args, apiKey, publishingTools, schedulerTools));
      } catch (error) {
        if (error instanceof ToolError && error.status === 404 && error.message.startsWith("Unknown tool")) {
          throw new RpcError(INVALID_PARAMS, error.message);
        }
        // Tool failures are results the model can read and react to.
        const message =
          error instanceof ToolError
            ? error.status === 401 || error.status === 403
              ? "Menivor rejected the API key. Create a current key at https://menivor.com/account/api-keys"
              : error.message
            : "The tool failed unexpectedly";
        return toolResult(message, true);
      }
    }
    default:
      throw new RpcError(METHOD_NOT_FOUND, `Method not found: ${String(message.method)}`);
  }
}

async function handle(
  message: unknown,
  apiKey: string | null,
  publishingTools: boolean,
  schedulerTools: boolean,
): Promise<JsonRpcResponse | null> {
  if (!message || typeof message !== "object" || Array.isArray(message)) {
    return { jsonrpc: "2.0", id: null, error: { code: INVALID_REQUEST, message: "Invalid request" } };
  }
  const request = message as JsonRpcRequest;
  const hasId = "id" in request && request.id !== undefined;
  const rpcId: JsonRpcId =
    typeof request.id === "string" || typeof request.id === "number" ? request.id : null;
  if (request.jsonrpc !== "2.0" || typeof request.method !== "string") {
    return hasId
      ? { jsonrpc: "2.0", id: rpcId, error: { code: INVALID_REQUEST, message: "Invalid request" } }
      : null;
  }
  // Notifications (no id) and client responses get no reply.
  if (!hasId) return null;
  try {
    return { jsonrpc: "2.0", id: rpcId, result: await dispatch(request, apiKey, publishingTools, schedulerTools) };
  } catch (error) {
    const rpc =
      error instanceof RpcError ? error : new RpcError(-32603, "Internal error");
    return { jsonrpc: "2.0", id: rpcId, error: { code: rpc.code, message: rpc.message } };
  }
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const length = Number(request.headers.get("content-length") ?? "0");
  if (length > MAX_BODY_BYTES) {
    return json({ jsonrpc: "2.0", id: null, error: { code: INVALID_REQUEST, message: "Body too large" } }, 413);
  }
  const raw = await request.text();
  if (raw.length > MAX_BODY_BYTES) {
    return json({ jsonrpc: "2.0", id: null, error: { code: INVALID_REQUEST, message: "Body too large" } }, 413);
  }
  let body: unknown;
  try {
    body = JSON.parse(raw);
  } catch {
    return json({ jsonrpc: "2.0", id: null, error: { code: PARSE_ERROR, message: "Parse error" } }, 400);
  }

  const apiKey = apiKeyFrom(request);
  const publishingTools = await mcpPublishingToolsEnabled();
  const schedulerTools = await mcpSchedulerToolsEnabled();
  const messages = Array.isArray(body) ? body : [body];
  if (messages.length === 0 || messages.length > MAX_BATCH) {
    return json(
      { jsonrpc: "2.0", id: null, error: { code: INVALID_REQUEST, message: `Send 1 to ${MAX_BATCH} messages` } },
      400,
    );
  }
  const replies = (
    await Promise.all(messages.map((message) => handle(message, apiKey, publishingTools, schedulerTools)))
  ).filter(
    (reply): reply is JsonRpcResponse => reply !== null,
  );
  if (replies.length === 0) return new NextResponse(null, { status: 202, headers: CORS_HEADERS });

  // An unauthenticated tools/call is also flagged at the HTTP layer so
  // clients that support OAuth-less bearer prompts can ask for the key.
  const unauthorized = replies.some((reply) => reply.error?.code === UNAUTHORIZED);
  const payload = Array.isArray(body) ? replies : replies[0];
  return unauthorized
    ? json(payload, 401, { "WWW-Authenticate": 'Bearer realm="menivor", error="invalid_token"' })
    : json(payload);
}

/** No server-initiated stream is offered on this stateless endpoint. */
export function GET(): NextResponse {
  return json(
    { jsonrpc: "2.0", id: null, error: { code: INVALID_REQUEST, message: "Use POST for MCP requests" } },
    405,
    { Allow: "POST, OPTIONS" },
  );
}

export function DELETE(): NextResponse {
  return GET();
}

export function OPTIONS(): NextResponse {
  return new NextResponse(null, { status: 204, headers: CORS_HEADERS });
}
