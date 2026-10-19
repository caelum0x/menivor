/**
 * Typed API layer barrel — all domains re-exported in one place.
 *
 * Import individual domains for explicit granularity:
 *   import { listJobs, createJob } from "@/lib/api/jobs";
 *
 * Or import everything from here:
 *   import { listJobs, listVoices, getAnalytics } from "@/lib/api";
 *   // (the above still works — this barrel does not shadow it)
 *
 * Domain breakdown:
 *   auth        — device session, file uploads / presign
 *   catalog     — read-only creator catalogs (caption-styles, music, layouts…)
 *   studio      — avatars, voices, me profile
 *   jobs        — create/list/poll reels, broll, social copy, share links
 *   insights    — analytics, notifications, performance, leaderboard
 *   billing     — plans, providers, checkout
 *   referral    — referral code + redeem
 *   presets     — saved job configs
 *   connections — OAuth connections + publishing
 *   workspaces  — team workspaces, RBAC, audit trail, admin
 *   developer   — API keys, usage, brand, creator profiles
 *   media       — ideas, marketplace, scheduled publishes
 *   motion      — camera-move catalog, detail, compile, render history
 *   wallet      — top-up, transfers, sources, destinations
 *
 * The shared primitives (ApiError, RequestOptions, API_BASE) are re-exported
 * from lib/api for convenience.
 */

export {
  API_BASE,
  ApiError,
  isAbortError,
  POLL_INTERVAL_MS,
  type RequestOptions,
} from "@/lib/api";

// Domain re-exports (subset — prefer importing from domain files for clarity)
export * from "./auth";
export * from "./billing";
export * from "./catalog";
export * from "./connections";
export * from "./developer";
export * from "./insights";
export * from "./jobs";
export * from "./media";
export * from "./motion";
export * from "./presets";
export * from "./referral";
export * from "./studio";
export * from "./wallet";
export * from "./workspaces";
