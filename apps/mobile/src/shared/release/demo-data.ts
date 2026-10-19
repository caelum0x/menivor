/**
 * Seeded demo workspace (dev-only, see isDemoMode). Real-looking projects across
 * the niches Menivor is built for, used for screenshots and walkthroughs. These
 * are never shown in a store build: apiRequest only consults them when
 * isDemoMode() is true, which requires a Metro dev session.
 */

import type { Job } from "@/lib/types";

export const DEMO_API_KEY = "demo-session";
export const DEMO_USER_ID = "demo-creator";

/** A fixed clock so the seeded timeline reads naturally in screenshots. */
const NOW = Date.parse("2026-10-06T09:41:00Z");
const minutesAgo = (minutes: number): string =>
  new Date(NOW - minutes * 60_000).toISOString();

const DONE = {
  script: "complete",
  tts: "complete",
  avatar: "complete",
  captions: "complete",
  compose: "complete",
  upload: "complete",
} as const;

export interface DemoProject {
  readonly job: Job;
  /** Niche label drawn on the code-rendered poster art. */
  readonly niche: string;
}

function project(
  id: string,
  niche: string,
  title: string,
  hook: string,
  minutes: number,
  overrides: Partial<Job> = {},
): DemoProject {
  return {
    niche,
    job: {
      job_id: id,
      kind: "reel",
      state: 1,
      progress: 100,
      stages: DONE,
      title,
      hook,
      language: "en",
      created_at: minutesAgo(minutes),
      brief_ready: true,
      ...overrides,
    },
  };
}

export const DEMO_PROJECTS: readonly DemoProject[] = [
  project(
    "demo-reel-lisbon",
    "Travel",
    "Lisbon in one golden hour",
    "You only need 60 minutes to fall for Lisbon.",
    6,
    {
      state: 4,
      progress: 62,
      stages: {
        script: "complete",
        tts: "complete",
        avatar: "complete",
        captions: "running",
        compose: "pending",
        upload: "pending",
      },
    },
  ),
  project(
    "demo-reel-knife",
    "Cooking",
    "3 knife cuts every home cook needs",
    "Stop crushing your herbs. Do this instead.",
    48,
  ),
  project(
    "demo-reel-mobility",
    "Fitness",
    "Morning mobility in 30 seconds",
    "Your hips will thank you by Friday.",
    190,
  ),
  project(
    "demo-reel-onboarding",
    "Product demo",
    "Onboarding in 40 seconds",
    "We deleted 6 screens and signups doubled.",
    1440,
  ),
  project(
    "demo-reel-loft",
    "Real estate",
    "The two-bedroom loft tour",
    "Wait until you see the window at 0:12.",
    2900,
  ),
  project(
    "demo-reel-sourdough",
    "Baking",
    "Why your sourdough goes flat",
    "It is not your starter. It is the fold.",
    4400,
  ),
];

export const DEMO_ME = {
  user_id: DEMO_USER_ID,
  email: "maya@studio-north.co",
  credits: 42,
  jobs_count: DEMO_PROJECTS.length,
} as const;

export const DEMO_INSIGHTS = {
  user_id: DEMO_USER_ID,
  jobs_total: DEMO_PROJECTS.length,
  jobs_by_state: { complete: 5, processing: 1 },
  credits_balance: 42,
  credits_spent: 18,
  total_cost_usd: 0,
  avg_render_ms: 94_000,
  videos_generated: 5,
} as const;

export const DEMO_LAUNCH_STATUS = {
  mode: "public",
  public_access: true,
  features: { signup: true, checkout: true, publishing: false },
} as const;

/** Niche for a seeded job id, used by the poster art. */
export function demoNicheFor(jobId: string): string | undefined {
  return DEMO_PROJECTS.find((p) => p.job.job_id === jobId)?.niche;
}
