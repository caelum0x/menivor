import { NextResponse } from "next/server";
import { clientIp, createRateLimiter, hashIp } from "@/lib/rate-limit";
import {
  buildPrompt,
  maxTokensFor,
  parseOutput,
  validateGenerateRequest,
} from "@/lib/seo/free-tools/generate";

/**
 * Free AI writing tools (/tools/tiktok-hook-generator etc.): browser -> this
 * route -> Railyard Relay (OpenAI-compatible) -> Claude Haiku.
 *
 * Env (Worker vars/secrets): RELAY_URL, RELAY_API_KEY (secret), optional
 * FREE_TOOLS_MODEL. Unset => 503 with a clear message.
 *
 * Abuse protection, layered:
 *  - same-origin check (Origin/Referer must be menivor.com in production),
 *  - Cloudflare Rate Limiting bindings (per hashed IP and a global key; they
 *    hold across isolates within a colo),
 *  - a per-isolate hourly bucket per hashed IP,
 *  - small bodies, 300-char topics, capped output tokens.
 * Nothing the visitor types is stored.
 */

const MAX_BODY_BYTES = 2048;
const RUNS_PER_HOUR = 12;
const HOUR_MS = 60 * 60 * 1000;
const UPSTREAM_TIMEOUT_MS = 25_000;
const DEFAULT_MODEL = "tensorzero::model_name::anthropic::claude-haiku-4-5";
const ALLOWED_ORIGINS = ["https://menivor.com", "https://www.menivor.com"];

const hourlyLimiter = createRateLimiter({ capacity: RUNS_PER_HOUR, refillMs: HOUR_MS });

interface RateLimitBinding {
  limit(options: { key: string }): Promise<{ success: boolean }>;
}

interface ToolsEnv {
  readonly RELAY_URL?: string;
  readonly RELAY_API_KEY?: string;
  readonly FREE_TOOLS_MODEL?: string;
  readonly TOOLS_IP_LIMITER?: RateLimitBinding;
  readonly TOOLS_GLOBAL_LIMITER?: RateLimitBinding;
}

function json(status: number, body: Record<string, unknown>): NextResponse {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

async function readEnv(): Promise<ToolsEnv> {
  try {
    const { getCloudflareContext } = await import("@opennextjs/cloudflare");
    const { env } = getCloudflareContext();
    return env as unknown as ToolsEnv;
  } catch {
    // Outside the Workers runtime (local dev/tests): fall back to process.env.
    return process.env as unknown as ToolsEnv;
  }
}

function sameOrigin(request: Request): boolean {
  if (process.env.NODE_ENV !== "production") return true;
  const origin = request.headers.get("origin") ?? request.headers.get("referer") ?? "";
  return ALLOWED_ORIGINS.some((allowed) => origin === allowed || origin.startsWith(`${allowed}/`));
}

async function edgeLimited(env: ToolsEnv, ipKey: string): Promise<boolean> {
  try {
    if (env.TOOLS_IP_LIMITER && !(await env.TOOLS_IP_LIMITER.limit({ key: ipKey })).success) {
      return true;
    }
    if (env.TOOLS_GLOBAL_LIMITER && !(await env.TOOLS_GLOBAL_LIMITER.limit({ key: "all" })).success) {
      return true;
    }
  } catch (error) {
    console.error(JSON.stringify({ event: "free_tools_ratelimit_error", message: String(error) }));
  }
  return false;
}

async function callRelay(env: ToolsEnv, prompt: string, maxTokens: number): Promise<string | null> {
  const base = (env.RELAY_URL ?? "").replace(/\/+$/, "");
  const response = await fetch(`${base}/openai/v1/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${env.RELAY_API_KEY}`,
    },
    body: JSON.stringify({
      model: env.FREE_TOOLS_MODEL || DEFAULT_MODEL,
      max_tokens: maxTokens,
      temperature: 0.9,
      messages: [{ role: "user", content: prompt }],
    }),
    signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
  });
  if (!response.ok) {
    console.error(JSON.stringify({ event: "free_tools_upstream_error", status: response.status }));
    return null;
  }
  const data = (await response.json()) as {
    choices?: Array<{ message?: { content?: unknown } }>;
  };
  const content = data.choices?.[0]?.message?.content;
  return typeof content === "string" ? content : null;
}

export async function POST(request: Request): Promise<NextResponse> {
  if (!sameOrigin(request)) return json(403, { ok: false, error: "Use the tool on menivor.com." });

  const env = await readEnv();
  const ip = clientIp(request);
  if (ip) {
    const ipKey = await hashIp(ip);
    const local = hourlyLimiter.check(ipKey);
    if (!local.allowed || (await edgeLimited(env, ipKey))) {
      const response = json(429, {
        ok: false,
        error: "You have used the free generator a lot in a short time. Try again in a little while, or create a free Menivor account to keep going.",
      });
      response.headers.set("Retry-After", String(local.allowed ? 60 : local.retryAfterSeconds));
      return response;
    }
  }

  const raw = await request.text().catch(() => null);
  if (raw === null) return json(400, { ok: false, error: "Could not read the request." });
  if (raw.length > MAX_BODY_BYTES) return json(413, { ok: false, error: "That is too long." });
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return json(400, { ok: false, error: "Request body must be JSON." });
  }
  const validation = validateGenerateRequest(parsed);
  if (!validation.ok) return json(400, { ok: false, error: validation.error });

  if (!env.RELAY_URL || !env.RELAY_API_KEY) {
    return json(503, { ok: false, error: "The generator is resting. Please try again soon." });
  }

  const req = validation.value;
  try {
    const text = await callRelay(env, buildPrompt(req), maxTokensFor(req.kind));
    const output = text ? parseOutput(req.kind, text) : null;
    if (!output) {
      return json(502, { ok: false, error: "The AI returned an unusable answer. Please try again." });
    }
    console.info(JSON.stringify({ event: "free_tool_run", kind: req.kind, platform: req.platform }));
    return json(200, { ok: true, output });
  } catch (error) {
    console.error(JSON.stringify({ event: "free_tools_error", message: String(error) }));
    return json(504, { ok: false, error: "The generator took too long. Please try again." });
  }
}
