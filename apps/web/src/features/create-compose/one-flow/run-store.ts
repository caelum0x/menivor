/**
 * Browser-local memory for a one-flow run: which hook each variant opened
 * with (link mode writes them before the pipeline does) and which variant
 * the creator picked. Purely a convenience layer; the results page works
 * from the job ids in the URL alone and falls back to each job's own `hook`.
 */

import type { HookAngleId, SourceKind } from "./plan";

export interface RunVariantMeta {
  readonly jobId: string;
  readonly angle?: HookAngleId;
  readonly hook?: string;
}

export interface RunMeta {
  readonly source: SourceKind;
  readonly input: string;
  readonly presetId: string;
  readonly startedAt: number;
  readonly variants: readonly RunVariantMeta[];
  /** Set when fewer variants started than requested (e.g. credits ran out). */
  readonly notice?: string;
}

const RUN_PREFIX = "menivor.create.run:";
const PICK_PREFIX = "menivor.create.pick:";

function runKey(jobIds: readonly string[]): string {
  return [...jobIds].sort().join(",");
}

function storage(kind: "session" | "local"): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return kind === "session" ? window.sessionStorage : window.localStorage;
  } catch {
    return null;
  }
}

function isRunMeta(value: unknown): value is RunMeta {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<RunMeta>;
  return (
    (candidate.source === "topic" || candidate.source === "link") &&
    typeof candidate.input === "string" &&
    typeof candidate.startedAt === "number" &&
    Array.isArray(candidate.variants)
  );
}

export function saveRun(meta: RunMeta): void {
  const store = storage("session");
  if (!store) return;
  try {
    store.setItem(
      RUN_PREFIX + runKey(meta.variants.map((v) => v.jobId)),
      JSON.stringify(meta),
    );
  } catch {
    // Storage full or blocked: the results page still works from the URL.
  }
}

export function loadRun(jobIds: readonly string[]): RunMeta | null {
  const store = storage("session");
  if (!store) return null;
  try {
    const raw = store.getItem(RUN_PREFIX + runKey(jobIds));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isRunMeta(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function savePick(jobIds: readonly string[], picked: string): void {
  const store = storage("local");
  if (!store) return;
  try {
    store.setItem(PICK_PREFIX + runKey(jobIds), picked);
  } catch {
    // Non-fatal: the pick simply is not remembered across reloads.
  }
}

export function loadPick(jobIds: readonly string[]): string {
  const store = storage("local");
  if (!store) return "";
  try {
    const value = store.getItem(PICK_PREFIX + runKey(jobIds)) ?? "";
    return jobIds.includes(value) ? value : "";
  } catch {
    return "";
  }
}
