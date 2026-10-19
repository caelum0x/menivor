/**
 * Pure, framework-free helpers for the Film / Series Studio flow.
 *
 * Kept separate from the React components so the plan→project translation, the
 * per-shot render-spec construction, and the render-progress aggregation can be
 * unit-tested without a renderer. No network, no React state.
 */

import type {
  BeatIn,
  CharacterIn,
  CreateProjectBody,
  FilmProjectShot,
} from "@/lib/film";
import { parseBeatLines } from "@/lib/film";
import {
  isTerminalState,
  type CreateRenderJobBody,
  type RenderJob,
  type RenderState,
} from "@/lib/render";

/** Default max spend per shot render (micros) — mirrors the render screen cap. */
export const SHOT_MAX_COST_MICROS = 100000;

/** Stable idempotency key for a project create (retained across retries). */
export function createProjectIdempotencyKey(): string {
  return `film-project-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * Parse a comma / newline separated descriptor blob into a clean string list.
 * Never mutates its input; empty entries are dropped.
 */
export function parseDescriptors(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((d) => d.trim())
    .filter((d) => d.length > 0);
}

export interface FilmStudioFormInput {
  title: string;
  characterId: string;
  characterName: string;
  descriptors: string;
  style: string;
  beatsText: string;
  totalShots: number;
  targetRuntimeS?: number;
}

/**
 * The keys of the required fields still missing before a film project can be
 * created, given the currently-entered values. Empty ⇒ ready to submit.
 */
export function missingProjectFields(input: FilmStudioFormInput): string[] {
  const missing: string[] = [];
  if (input.title.trim().length === 0) missing.push("title");
  if (input.characterId.trim().length === 0) missing.push("characterId");
  if (input.characterName.trim().length === 0) missing.push("characterName");
  if (parseBeatLines(input.beatsText).length === 0) missing.push("beats");
  return missing;
}

/**
 * Translate the studio form into a valid `POST /film/projects` body: the beats
 * blob becomes {@link BeatIn}[], the identity fields become a {@link CharacterIn},
 * and the sizing knobs pass through. Optional fields are omitted when empty so
 * the request stays clean. Never mutates its argument.
 */
export function buildCreateProjectBody(
  input: FilmStudioFormInput,
): CreateProjectBody {
  const beats: BeatIn[] = parseBeatLines(input.beatsText);
  const descriptors = parseDescriptors(input.descriptors);
  const style = input.style.trim();

  const character: CharacterIn = {
    character_id: input.characterId.trim(),
    name: input.characterName.trim(),
    ...(descriptors.length > 0 ? { descriptors } : {}),
    ...(style ? { style } : {}),
  };

  return {
    title: input.title.trim(),
    beats,
    character,
    total_shots: input.totalShots,
    ...(input.targetRuntimeS !== undefined && input.targetRuntimeS > 0
      ? { target_runtime_s: input.targetRuntimeS }
      : {}),
  };
}

/**
 * Build the `POST /render/jobs` spec for one persisted shot. The identity-locked
 * prompt drives the render; the per-shot cost cap protects the caller's budget.
 */
export function buildShotRenderBody(
  shot: Pick<FilmProjectShot, "prompt">,
  maxCostMicros: number = SHOT_MAX_COST_MICROS,
): CreateRenderJobBody {
  return {
    backend: "runpod",
    spec: { prompt: shot.prompt },
    max_cost_micros: maxCostMicros,
  };
}

export type ShotRenderPhase = "idle" | "queued" | "running" | "completed" | "failed";

/** The render phase for a shot given its (optional) latest render job snapshot. */
export function shotRenderPhase(job: RenderJob | undefined): ShotRenderPhase {
  if (!job) return "idle";
  if (job.state === "FAILED" || job.state === "CANCELLED") return "failed";
  if (job.state === "COMPLETED") return "completed";
  return job.progress > 0 ? "running" : "queued";
}

/**
 * The overall completion ratio (0..1) across a film's shots, given the render
 * job map keyed by `shot_id`. Un-started shots count as 0; a shot with no job
 * contributes 0. Returns 0 for an empty film.
 */
export function overallRenderProgress(
  shots: readonly FilmProjectShot[],
  jobs: Readonly<Record<string, RenderJob | undefined>>,
): number {
  if (shots.length === 0) return 0;
  const sum = shots.reduce((acc, shot) => {
    const job = jobs[shot.shot_id];
    if (!job) return acc;
    return acc + (job.state === "COMPLETED" ? 1 : Math.min(Math.max(job.progress, 0), 1));
  }, 0);
  return sum / shots.length;
}

/** True once every shot has a render job in a terminal state (all done/failed). */
export function allShotsTerminal(
  shots: readonly FilmProjectShot[],
  jobs: Readonly<Record<string, RenderJob | undefined>>,
): boolean {
  if (shots.length === 0) return false;
  return shots.every((shot) => {
    const job = jobs[shot.shot_id];
    return job !== undefined && isTerminalState(job.state);
  });
}

/** A render state is still advancing (worth another poll). */
export function isPollableState(state: RenderState): boolean {
  return !isTerminalState(state);
}
