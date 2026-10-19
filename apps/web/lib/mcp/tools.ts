/**
 * Menivor MCP tools: the tool catalog served by the remote MCP endpoint at
 * `/api/mcp`, each one a thin, typed proxy over the public REST API.
 *
 * Every tool authenticates with the caller's own personal API key (created at
 * /account/api-keys) sent as `x-api-key`, so an agent can do exactly what the
 * key's owner can do through the REST API and nothing more. Arguments are
 * validated here before any upstream call; the API still validates again.
 */

import { API_BASE } from "@/src/shared/api/base";

/** JSON Schema for one tool's arguments (the MCP `inputSchema`). */
export interface ToolInputSchema {
  readonly type: "object";
  readonly properties: Readonly<Record<string, unknown>>;
  readonly required?: readonly string[];
  readonly additionalProperties?: boolean;
}

export interface McpToolDefinition {
  readonly name: string;
  readonly title: string;
  readonly description: string;
  readonly inputSchema: ToolInputSchema;
  readonly annotations?: Readonly<{
    readOnlyHint?: boolean;
    destructiveHint?: boolean;
    idempotentHint?: boolean;
    openWorldHint?: boolean;
  }>;
}

/** An upstream failure, reported to the agent as a tool error. */
export class ToolError extends Error {
  readonly status: number;
  constructor(message: string, status = 400) {
    super(message);
    this.name = "ToolError";
    this.status = status;
  }
}

type Args = Readonly<Record<string, unknown>>;

interface Tool extends McpToolDefinition {
  readonly run: (args: Args, apiKey: string) => Promise<unknown>;
}

const PLATFORMS = ["tiktok", "instagram", "youtube_shorts"] as const;
const ASPECTS = ["9:16", "16:9", "1:1"] as const;
const AD_FORMATS = ["showcase", "before_after", "ugc_avatar"] as const;
const UPSTREAM_TIMEOUT_MS = 30_000;

// ── argument helpers ────────────────────────────────────────────────────────

function str(args: Args, key: string, options: { required?: boolean; max?: number } = {}): string | undefined {
  const value = args[key];
  if (value === undefined || value === null || value === "") {
    if (options.required) throw new ToolError(`"${key}" is required`);
    return undefined;
  }
  if (typeof value !== "string") throw new ToolError(`"${key}" must be a string`);
  const trimmed = value.trim();
  if (options.required && !trimmed) throw new ToolError(`"${key}" is required`);
  if (options.max !== undefined && trimmed.length > options.max) {
    throw new ToolError(`"${key}" must be at most ${options.max} characters`);
  }
  return trimmed || undefined;
}

function oneOf<T extends string>(args: Args, key: string, allowed: readonly T[]): T | undefined {
  const value = str(args, key);
  if (value === undefined) return undefined;
  if (!(allowed as readonly string[]).includes(value)) {
    throw new ToolError(`"${key}" must be one of: ${allowed.join(", ")}`);
  }
  return value as T;
}

function listOf<T extends string>(
  args: Args,
  key: string,
  allowed: readonly T[],
  options: { required?: boolean } = {},
): T[] | undefined {
  const value = args[key];
  if (value === undefined || value === null) {
    if (options.required) throw new ToolError(`"${key}" is required`);
    return undefined;
  }
  if (!Array.isArray(value) || value.length === 0) {
    throw new ToolError(`"${key}" must be a non-empty array`);
  }
  const bad = value.filter((item) => !(allowed as readonly unknown[]).includes(item));
  if (bad.length > 0) throw new ToolError(`"${key}" accepts only: ${allowed.join(", ")}`);
  return [...new Set(value as T[])];
}

function int(args: Args, key: string, min: number, max: number): number | undefined {
  const value = args[key];
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "number" || !Number.isInteger(value) || value < min || value > max) {
    throw new ToolError(`"${key}" must be an integer from ${min} to ${max}`);
  }
  return value;
}

/** Opaque ids go into URL paths, so only safe id characters are accepted. */
function id(args: Args, key: string): string {
  const value = str(args, key, { required: true, max: 128 }) as string;
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new ToolError(`"${key}" is not a valid id`);
  return value;
}

function compact(record: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(record).filter(([, value]) => value !== undefined));
}

// ── upstream transport ──────────────────────────────────────────────────────

interface Envelope {
  readonly data?: unknown;
  readonly message?: unknown;
}

/** Calls the REST API with the caller's key and unwraps the `{data}` envelope. */
export async function callApi(
  apiKey: string,
  path: string,
  init: { method?: "GET" | "POST"; body?: unknown } = {},
): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: init.method ?? "GET",
      headers: {
        "x-api-key": apiKey,
        Accept: "application/json",
        ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (error) {
    throw new ToolError(
      error instanceof Error && error.name === "AbortError"
        ? "The Menivor API did not answer in time"
        : "Could not reach the Menivor API",
      502,
    );
  } finally {
    clearTimeout(timer);
  }
  const raw = await response.text();
  let parsed: Envelope | null = null;
  try {
    parsed = raw ? (JSON.parse(raw) as Envelope) : null;
  } catch {
    parsed = null;
  }
  if (!response.ok) {
    const message =
      typeof parsed?.message === "string" && parsed.message
        ? parsed.message
        : `Menivor API returned HTTP ${response.status}`;
    throw new ToolError(message, response.status);
  }
  return parsed && "data" in parsed ? parsed.data : parsed;
}

// ── tools ───────────────────────────────────────────────────────────────────

const TOOLS: readonly Tool[] = [
  {
    name: "create_reel",
    title: "Create a reel",
    description:
      "Start rendering a vertical short-form reel. Uses one reel credit per variant, reserved at start and released if the render fails. Returns job_id; poll it with get_job.",
    inputSchema: {
      type: "object",
      properties: {
        subject: { type: "string", description: "What the reel is about (the topic or hook)", maxLength: 500 },
        script: { type: "string", description: "Optional narration script; generated from the subject when omitted", maxLength: 5000 },
        language: { type: "string", description: "Script language code, e.g. en or tr; defaults to auto", maxLength: 8 },
        aspect: { type: "string", enum: [...ASPECTS], description: "Output aspect ratio; defaults to 9:16" },
        voice_name: { type: "string", description: "Voice id from GET /voices", maxLength: 128 },
        avatar_id: { type: "string", description: "Avatar presenter id from GET /avatars", maxLength: 128 },
        screen_recording_key: { type: "string", description: "Key of an uploaded screen recording you own", maxLength: 512 },
        caption_style: { type: "string", description: "Caption style id", maxLength: 64 },
        variants: { type: "integer", minimum: 1, maximum: 3, description: "Render 1 to 3 variants; each uses one credit" },
      },
      required: ["subject"],
      additionalProperties: false,
    },
    annotations: { destructiveHint: false, openWorldHint: true },
    run: (args, apiKey) => {
      const params = compact({
        video_subject: str(args, "subject", { required: true, max: 500 }),
        video_script: str(args, "script", { max: 5000 }),
        language: str(args, "language", { max: 8 }),
        aspect: oneOf(args, "aspect", ASPECTS),
        voice_name: str(args, "voice_name", { max: 128 }),
        avatar_id: str(args, "avatar_id", { max: 128 }),
        screen_recording_key: str(args, "screen_recording_key", { max: 512 }),
      });
      return callApi(apiKey, "/jobs", {
        method: "POST",
        body: compact({
          params,
          caption_style: str(args, "caption_style", { max: 64 }),
          variants: int(args, "variants", 1, 3),
        }),
      });
    },
  },
  {
    name: "get_job",
    title: "Get a job",
    description: "Read a reel job's state, progress and, once finished, its download URL.",
    inputSchema: {
      type: "object",
      properties: { job_id: { type: "string", description: "Job id returned by create_reel" } },
      required: ["job_id"],
      additionalProperties: false,
    },
    annotations: { readOnlyHint: true },
    run: (args, apiKey) => callApi(apiKey, `/jobs/${encodeURIComponent(id(args, "job_id"))}`),
  },
  {
    name: "ad_from_url",
    title: "Ads from a product URL",
    description:
      "Extract a product from a URL and draft ad angles as an Ad Studio project. With render=true, also renders ad variants for every angle in the chosen formats and aspects.",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string", format: "uri", description: "Product or landing page URL", maxLength: 2048 },
        title: { type: "string", description: "Optional project title", maxLength: 200 },
        language: { type: "string", description: "Ad language code, e.g. en", maxLength: 5 },
        render: { type: "boolean", description: "Render variants right away (uses credits)" },
        formats: { type: "array", items: { type: "string", enum: [...AD_FORMATS] }, description: "Ad formats to render" },
        aspects: { type: "array", items: { type: "string", enum: [...ASPECTS] }, description: "Aspect ratios to render" },
        avatar_id: { type: "string", description: "Avatar presenter id; required for the ugc_avatar format", maxLength: 64 },
      },
      required: ["url"],
      additionalProperties: false,
    },
    annotations: { openWorldHint: true },
    run: async (args, apiKey) => {
      const url = str(args, "url", { required: true, max: 2048 }) as string;
      if (!/^https?:\/\//i.test(url)) throw new ToolError('"url" must start with http:// or https://');
      const project = (await callApi(apiKey, "/ad-studio/projects", {
        method: "POST",
        body: compact({
          url,
          title: str(args, "title", { max: 200 }),
          language: str(args, "language", { max: 5 }),
        }),
      })) as { id?: string; angles?: Array<{ id?: string }> };
      if (args.render !== true) return project;
      const angleIds = (project.angles ?? [])
        .map((angle) => angle.id)
        .filter((value): value is string => typeof value === "string")
        .slice(0, 5);
      if (!project.id || angleIds.length === 0) {
        throw new ToolError("The project has no ad angles to render", 422);
      }
      const variants = await callApi(
        apiKey,
        `/ad-studio/projects/${encodeURIComponent(project.id)}/variants`,
        {
          method: "POST",
          body: {
            angle_ids: angleIds,
            formats: listOf(args, "formats", AD_FORMATS) ?? ["showcase"],
            aspects: listOf(args, "aspects", ASPECTS) ?? ["9:16"],
            ...compact({ avatar_id: str(args, "avatar_id", { max: 64 }) }),
          },
        },
      );
      return { project, variants };
    },
  },
  {
    name: "schedule_publish",
    title: "Schedule publishing",
    description:
      "Schedule a finished reel to auto-publish to connected TikTok, Instagram or YouTube Shorts accounts at a future UTC time.",
    inputSchema: {
      type: "object",
      properties: {
        job_id: { type: "string", description: "A completed reel job id" },
        platforms: { type: "array", items: { type: "string", enum: [...PLATFORMS] }, minItems: 1 },
        scheduled_at: { type: "string", format: "date-time", description: "Future ISO-8601 UTC time" },
        youtube_privacy_status: { type: "string", enum: ["private", "unlisted", "public"] },
      },
      required: ["job_id", "platforms", "scheduled_at"],
      additionalProperties: false,
    },
    annotations: { openWorldHint: true },
    run: (args, apiKey) => {
      const when = str(args, "scheduled_at", { required: true, max: 64 }) as string;
      if (Number.isNaN(Date.parse(when))) throw new ToolError('"scheduled_at" must be an ISO-8601 time');
      return callApi(apiKey, `/jobs/${encodeURIComponent(id(args, "job_id"))}/schedule`, {
        method: "POST",
        body: compact({
          platforms: listOf(args, "platforms", PLATFORMS, { required: true }),
          scheduled_at: when,
          youtube_privacy_status: oneOf(args, "youtube_privacy_status", ["private", "unlisted", "public"] as const),
        }),
      });
    },
  },
  {
    name: "list_scheduled",
    title: "List scheduled posts",
    description: "List your scheduled publishes and their status.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: { readOnlyHint: true },
    run: (_args, apiKey) => callApi(apiKey, "/me/scheduled"),
  },
  {
    name: "get_performance",
    title: "Get performance",
    description:
      "Read logged performance (views, likes, retention) for one reel with job_id, or your most recent logged reels without it.",
    inputSchema: {
      type: "object",
      properties: {
        job_id: { type: "string", description: "Optional reel job id" },
        limit: { type: "integer", minimum: 1, maximum: 100, description: "Rows when listing; default 20" },
      },
      additionalProperties: false,
    },
    annotations: { readOnlyHint: true },
    run: (args, apiKey) =>
      args.job_id !== undefined
        ? callApi(apiKey, `/jobs/${encodeURIComponent(id(args, "job_id"))}/performance`)
        : callApi(apiKey, `/me/performance?limit=${int(args, "limit", 1, 100) ?? 20}`),
  },
  {
    name: "generation_quote",
    title: "Quote a generation",
    description:
      "Get a signed price quote before generating: name a generation profile, or map pipeline stages to catalog model ids. Optionally cap the budget.",
    inputSchema: {
      type: "object",
      properties: {
        profile: { type: "string", description: "Generation profile slug", maxLength: 128 },
        stages: {
          type: "object",
          additionalProperties: { type: "string" },
          description: "Stage to catalog model id, e.g. {\"voice\": \"elevenlabs/multilingual-v2\"}",
        },
        max_cost_usd: { type: "string", description: "Budget cap as a decimal USD string, e.g. \"2.50\"" },
      },
      additionalProperties: false,
    },
    annotations: { readOnlyHint: true },
    run: (args, apiKey) => {
      const stages = args.stages;
      if (stages !== undefined) {
        const valid =
          typeof stages === "object" &&
          stages !== null &&
          !Array.isArray(stages) &&
          Object.values(stages).every((value) => typeof value === "string");
        if (!valid) throw new ToolError('"stages" must map stage names to model id strings');
      }
      const profile = str(args, "profile", { max: 128 });
      if (!profile && stages === undefined) throw new ToolError('Pass "profile" or "stages"');
      const cap = str(args, "max_cost_usd", { max: 16 });
      if (cap !== undefined && !/^\d+(\.\d{1,6})?$/.test(cap)) {
        throw new ToolError('"max_cost_usd" must be a decimal like "2.50"');
      }
      return callApi(apiKey, "/catalog/quotes/generation", {
        method: "POST",
        body: compact({ profile, stages, max_cost_usd: cap }),
      });
    },
  },
  {
    name: "wallet_balance",
    title: "Wallet balance",
    description: "Read your Menivor wallet: available and reserved balance in USD.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: { readOnlyHint: true },
    run: (_args, apiKey) => callApi(apiKey, "/wallet"),
  },
  {
    name: "list_media_models",
    title: "List media models",
    description:
      "List Menivor's image, video and audio generation models with their integer micro-USD prices (per image, per second of video, or per audio clip).",
    inputSchema: {
      type: "object",
      properties: { modality: { type: "string", enum: ["image", "video", "audio"] } },
      additionalProperties: false,
    },
    annotations: { readOnlyHint: true },
    run: (args, apiKey) => {
      const modality = oneOf(args, "modality", ["image", "video", "audio"] as const);
      return callApi(apiKey, `/media/models${modality ? `?modality=${modality}` : ""}`);
    },
  },
];

const BY_NAME: ReadonlyMap<string, Tool> = new Map(TOOLS.map((tool) => [tool.name, tool]));

/** The public tool list for `tools/list` (no handlers). */
export function listTools(): McpToolDefinition[] {
  return TOOLS.map(({ run: _run, ...definition }) => definition);
}

/**
 * Tools that post to social platforms. They stay on the server (the API
 * answers `publishing_closed` while posting is closed), but public pages do
 * not list them as capabilities until posting opens (claims rule 5).
 */
export const PUBLISHING_TOOL_NAMES: ReadonlySet<string> = new Set(["schedule_publish", "list_scheduled"]);

/** The tools a public page may present as available today. */
export function listLiveTools(): McpToolDefinition[] {
  return listTools().filter((tool) => !PUBLISHING_TOOL_NAMES.has(tool.name));
}

/** Runs one tool; throws ToolError for bad input or an upstream failure. */
export async function runTool(name: string, args: unknown, apiKey: string): Promise<unknown> {
  const tool = BY_NAME.get(name);
  if (!tool) throw new ToolError(`Unknown tool: ${name}`, 404);
  if (args !== undefined && (typeof args !== "object" || args === null || Array.isArray(args))) {
    throw new ToolError("Tool arguments must be an object");
  }
  return tool.run((args ?? {}) as Args, apiKey);
}
