/**
 * Local answers for the seeded demo workspace. Read-only: GETs for seeded
 * resources resolve, everything else fails like an unavailable feature so no
 * screen pretends a write succeeded.
 */

import {
  DEMO_INSIGHTS,
  DEMO_LAUNCH_STATUS,
  DEMO_ME,
  DEMO_PROJECTS,
} from "./demo-data";

export class DemoUnavailableError extends Error {
  readonly status = 503;
  constructor(path: string) {
    super(`Not part of the demo workspace: ${path}`);
    this.name = "DemoUnavailableError";
  }
}

const JOB_PATH = /^\/jobs\/([^/?]+)$/;

/** Resolve a demo GET, or throw DemoUnavailableError. */
export function demoResponse(method: string, path: string): unknown {
  const bare = path.split("?", 1)[0] ?? path;
  if (method.toUpperCase() !== "GET") throw new DemoUnavailableError(bare);
  if (bare === "/me") return DEMO_ME;
  if (bare === "/me/insights" || bare === "/insights") return DEMO_INSIGHTS;
  if (bare === "/launch/status") return DEMO_LAUNCH_STATUS;
  if (bare === "/jobs") return DEMO_PROJECTS.map((p) => p.job);
  if (bare === "/me/presets") return [];
  if (bare === "/me/notifications") return { notifications: [], unread_count: 0 };
  if (bare === "/me/notifications/unread_count") return { unread_count: 0 };
  const job = JOB_PATH.exec(bare);
  if (job) {
    const found = DEMO_PROJECTS.find((p) => p.job.job_id === decodeURIComponent(job[1] ?? ""));
    if (found) return found.job;
  }
  throw new DemoUnavailableError(bare);
}
