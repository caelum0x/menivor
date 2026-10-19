/**
 * Menivor public API catalog — typed data module powering the /api-docs page.
 *
 * Each entry describes a real endpoint on the /api/v1 surface: path, method,
 * authentication requirement, query/body parameters, and a representative
 * example request. The data is static (no network call) so the reference page
 * renders instantly and works offline.
 *
 * Endpoints documented here are the subset published for third-party consumers:
 *   - Reel lifecycle (POST /jobs, GET /jobs/{id}, GET /jobs)
 *   - Shot-template catalog (GET /templates, GET /templates/{slug})
 *   - Live trend feed (GET /trends/recommended)
 *   - Creator analytics (GET /me/analytics)
 */

export type ParamKind = "query" | "body" | "path";

export interface EndpointParam {
  name: string;
  kind: ParamKind;
  type: string;
  required: boolean;
  description: string;
  example?: string;
}

export interface EndpointEntry {
  /** Method + path label, e.g. "POST /jobs". */
  id: string;
  method: "GET" | "POST" | "DELETE" | "PATCH";
  path: string;
  summary: string;
  description: string;
  /** Whether a caller key (x-api-key) is required. */
  authenticated: boolean;
  params: EndpointParam[];
  /** Condensed example cURL command. */
  exampleCurl: string;
  /** Representative JSON response shape. */
  responseShape: string;
  /** Logical grouping for the sidebar. */
  group: "reels" | "templates" | "trends" | "analytics";
}

export const API_CATALOG: EndpointEntry[] = [
  // -------------------------------------------------------------------------
  // Reels
  // -------------------------------------------------------------------------
  {
    id: "POST /jobs",
    method: "POST",
    path: "/jobs",
    summary: "Create a reel job",
    description:
      "Submit a new avatar-reel render job. The pipeline writes a hook-driven script, synthesises a voiceover, lip-syncs a HeyGen presenter, burns karaoke captions, and renders a 9:16 MP4. One credit is debited on submission and refunded if the render fails.",
    authenticated: true,
    group: "reels",
    params: [
      {
        name: "params.video_subject",
        kind: "body",
        type: "string",
        required: true,
        description: "Topic brief for the AI script generator.",
        example: '"How to set up Stripe webhooks in 60 seconds"',
      },
      {
        name: "params.voice_name",
        kind: "body",
        type: "string",
        required: true,
        description:
          'ElevenLabs voice id prefixed with "elevenlabs:", e.g. "elevenlabs:21m00Tcm4TlvDq8ikWAM".',
        example: '"elevenlabs:21m00Tcm4TlvDq8ikWAM"',
      },
      {
        name: "params.avatar_id",
        kind: "body",
        type: "string",
        required: true,
        description: "HeyGen avatar id or stored preset id.",
        example: '"Angela-inTshirt-20220820"',
      },
      {
        name: "params.layout",
        kind: "body",
        type: '"pip" | "hook_intro" | "split" | "captions_only"',
        required: true,
        description: "Composition layout the compose stage renders.",
        example: '"pip"',
      },
      {
        name: "params.aspect",
        kind: "body",
        type: '"9:16" | "1:1" | "16:9"',
        required: false,
        description: "Output aspect ratio. Defaults to 9:16 (vertical).",
        example: '"9:16"',
      },
      {
        name: "params.language",
        kind: "body",
        type: '"en" | "tr" | "auto"',
        required: false,
        description: "Script language. auto detects from the subject.",
        example: '"en"',
      },
      {
        name: "variants",
        kind: "body",
        type: "number (1–3)",
        required: false,
        description: "Fan out N A/B variants in a single request.",
        example: "1",
      },
    ],
    exampleCurl: `curl -X POST https://api.menivor.com/api/v1/jobs \\
  -H "x-api-key: <your-api-key>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "params": {
      "video_subject": "How to set up Stripe webhooks in 60 seconds",
      "voice_name": "elevenlabs:21m00Tcm4TlvDq8ikWAM",
      "avatar_id": "Angela-inTshirt-20220820",
      "layout": "pip",
      "aspect": "9:16",
      "language": "en",
      "caption_style": "karaoke_yellow",
      "target_duration_s": 60,
      "platforms": ["tiktok", "instagram"]
    }
  }'`,
    responseShape: `{
  "status": 200,
  "data": {
    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "state": 1,
    "progress": 0,
    "correlation_id": "req_abc123"
  }
}`,
  },
  {
    id: "GET /jobs/{job_id}",
    method: "GET",
    path: "/jobs/{job_id}",
    summary: "Get job status",
    description:
      "Poll this endpoint after creating a job. Returns the render state (1=pending, 2=processing, 3=complete, 4=failed), per-stage progress, and—once complete—a presigned result_url valid for 1 hour.",
    authenticated: true,
    group: "reels",
    params: [
      {
        name: "job_id",
        kind: "path",
        type: "string (UUID)",
        required: true,
        description: "The job id returned by POST /jobs.",
        example: '"3fa85f64-5717-4562-b3fc-2c963f66afa6"',
      },
    ],
    exampleCurl: `curl https://api.menivor.com/api/v1/jobs/3fa85f64-5717-4562-b3fc-2c963f66afa6 \\
  -H "x-api-key: <your-api-key>"`,
    responseShape: `{
  "status": 200,
  "data": {
    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "state": 3,
    "progress": 100,
    "result_url": "https://r2.menivor.com/results/...?X-Amz-Signature=...",
    "stages": {
      "script": "complete",
      "tts": "complete",
      "avatar": "complete",
      "captions": "complete",
      "compose": "complete"
    },
    "hook": "Stripe webhooks took me 4 hours. Here is the 60-second version."
  }
}`,
  },
  {
    id: "GET /jobs",
    method: "GET",
    path: "/jobs",
    summary: "List your jobs",
    description:
      "Returns the authenticated caller's jobs newest-first. Paginate with limit (1–100) and offset. Each item is the same shape as GET /jobs/{id}.",
    authenticated: true,
    group: "reels",
    params: [
      {
        name: "limit",
        kind: "query",
        type: "number",
        required: false,
        description: "Page size, clamped to 1–100. Default 50.",
        example: "20",
      },
      {
        name: "offset",
        kind: "query",
        type: "number",
        required: false,
        description: "Row offset for pagination. Default 0.",
        example: "0",
      },
    ],
    exampleCurl: `curl "https://api.menivor.com/api/v1/jobs?limit=20&offset=0" \\
  -H "x-api-key: <your-api-key>"`,
    responseShape: `{
  "status": 200,
  "data": {
    "jobs": [
      { "job_id": "...", "state": 3, "progress": 100, "result_url": "..." },
      ...
    ]
  }
}`,
  },

  // -------------------------------------------------------------------------
  // Templates
  // -------------------------------------------------------------------------
  {
    id: "GET /templates",
    method: "GET",
    path: "/templates",
    summary: "List shot-templates",
    description:
      "Returns the full catalog of seeded viral-genre shot-templates (Minecraft-split, ASMR, recap, tutorial, etc.). No authentication required. Each summary includes the genre, layout, default duration, and slot count.",
    authenticated: false,
    group: "templates",
    params: [],
    exampleCurl: `curl https://api.menivor.com/api/v1/templates`,
    responseShape: `{
  "status": 200,
  "data": {
    "templates": [
      {
        "slug": "minecraft_split",
        "name": "Minecraft Split",
        "genre": "split_screen",
        "version": "1.0.0",
        "layout": "split",
        "default_duration_s": 60,
        "slot_count": 3,
        "tags": ["gaming", "tutorial"]
      },
      ...
    ]
  }
}`,
  },
  {
    id: "GET /templates/{slug}",
    method: "GET",
    path: "/templates/{slug}",
    summary: "Get a shot-template",
    description:
      "Returns the full template definition including segment slots, required inputs, VFX intensity, and the audio spec. Use this to render a slot-by-slot breakdown in a template picker UI.",
    authenticated: false,
    group: "templates",
    params: [
      {
        name: "slug",
        kind: "path",
        type: "string",
        required: true,
        description: "Template slug from the catalog (e.g. minecraft_split).",
        example: '"minecraft_split"',
      },
    ],
    exampleCurl: `curl https://api.menivor.com/api/v1/templates/minecraft_split`,
    responseShape: `{
  "status": 200,
  "data": {
    "slug": "minecraft_split",
    "name": "Minecraft Split",
    "slots": [
      { "role": "hook", "order": 0, "label": "Hook clip", "track": "background" },
      ...
    ],
    "inputs": [
      { "key": "subject", "kind": "text", "label": "What is the video about?", "required": true }
    ]
  }
}`,
  },

  // -------------------------------------------------------------------------
  // Trends
  // -------------------------------------------------------------------------
  {
    id: "GET /trends/recommended",
    method: "GET",
    path: "/trends/recommended",
    summary: "Live recommended trends",
    description:
      "Returns server-ranked rising trends (sounds, hashtags, viral formats) scored by velocity and saturation. Results are highest-opportunity first — build content before the phase tips from rising to peaked.",
    authenticated: false,
    group: "trends",
    params: [
      {
        name: "limit",
        kind: "query",
        type: "number",
        required: false,
        description: "Max results to return. Default 30.",
        example: "20",
      },
    ],
    exampleCurl: `curl "https://api.menivor.com/api/v1/trends/recommended?limit=20"`,
    responseShape: `{
  "status": 200,
  "data": {
    "trends": [
      {
        "id": "tr_abc",
        "trend_id": "sound_calm_lo_fi_beats",
        "kind": "sound",
        "label": "Calm lo-fi beats",
        "opportunity": 0.87,
        "saturation": 0.12,
        "phase": "rising",
        "recommend": true
      },
      ...
    ]
  }
}`,
  },

  // -------------------------------------------------------------------------
  // Analytics
  // -------------------------------------------------------------------------
  {
    id: "GET /me/analytics",
    method: "GET",
    path: "/me/analytics",
    summary: "Creator analytics dashboard",
    description:
      "Returns the authenticated caller's BI analytics for a trailing window: job funnel (created/completed/failed/published), daily cost and credit burn, render-time percentiles, usage breakdowns by layout and language, and most-used templates and hook lines. Strictly scoped to the caller—never leaks another user's data.",
    authenticated: true,
    group: "analytics",
    params: [
      {
        name: "days",
        kind: "query",
        type: "number (1–365)",
        required: false,
        description: "Trailing window size in days. Default 30.",
        example: "30",
      },
    ],
    exampleCurl: `curl "https://api.menivor.com/api/v1/me/analytics?days=30" \\
  -H "x-api-key: <your-api-key>"`,
    responseShape: `{
  "status": 200,
  "data": {
    "user_id": "usr_abc",
    "days": 30,
    "funnel": { "created": 24, "completed": 20, "failed": 2, "published": 14 },
    "cost_by_day": [{ "date": "2026-09-01", "cost_usd": 1.20 }, ...],
    "credits": { "balance": 47, "spent": 20, "burn_by_day": [...] },
    "render_time": { "p50_ms": 42000, "p90_ms": 68000, "avg_ms": 45000, "samples": 20 },
    "by_layout": { "pip": 14, "split": 4, "captions_only": 2 },
    "by_language": { "en": 18, "tr": 2 },
    "totals": { "jobs_total": 24, "videos_generated": 20, "total_cost_usd": 24.00 },
    "top_content": {
      "templates": [{ "name": "minecraft_split", "count": 6 }],
      "hooks": [{ "hook": "You are doing this wrong.", "count": 4 }]
    }
  }
}`,
  },
];

/** The distinct groups in catalog order. */
export const CATALOG_GROUPS: Array<EndpointEntry["group"]> = [
  "reels",
  "templates",
  "trends",
  "analytics",
];

/** Display label for each group. */
export const GROUP_LABELS: Record<EndpointEntry["group"], string> = {
  reels: "Reels",
  templates: "Templates",
  trends: "Trends",
  analytics: "Analytics",
};
