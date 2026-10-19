/**
 * Device-local memory for a one-flow run: which hook each variant opened with
 * (link mode writes them before the pipeline does), the run's winner-loop
 * batch id, and which variant the creator picked. Purely a convenience layer:
 * the results screen works from the job ids in its route alone and falls back
 * to each job's own `hook`.
 *
 * Stored in AsyncStorage so a run survives the app being closed mid-render.
 * The (de)serialisers are pure and unit-tested; the storage calls never throw.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";

import { isHookStyle, type HookAngleId, type SourceKind } from "./plan";

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
  /** The run's shared batch id: the winner-loop project for this run. */
  readonly batchId?: string;
  /** Set when fewer variants started than requested (e.g. credits ran out). */
  readonly notice?: string;
}

const RUN_PREFIX = "menivor.create.run.v1:";
const PICK_PREFIX = "menivor.create.pick.v1:";
const JOB_BATCH_PREFIX = "menivor.create.job-batch.v1:";
const BATCH_ID_PATTERN = /^[A-Za-z0-9_-]{6,64}$/;

/** Order-independent storage key for a run's job ids. */
export function runKey(jobIds: readonly string[]): string {
  return [...jobIds].sort().join(",");
}

function parseVariant(value: unknown): RunVariantMeta | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (typeof row.jobId !== "string" || !row.jobId) return null;
  return {
    jobId: row.jobId,
    ...(isHookStyle(row.angle) ? { angle: row.angle } : {}),
    ...(typeof row.hook === "string" && row.hook ? { hook: row.hook } : {}),
  };
}

/** Parse a stored run, or null when it is missing or malformed. */
export function parseRunMeta(raw: string | null): RunMeta | null {
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const row = parsed as Record<string, unknown>;
  if (row.source !== "topic" && row.source !== "link") return null;
  if (typeof row.input !== "string" || typeof row.startedAt !== "number") return null;
  if (!Array.isArray(row.variants)) return null;
  const variants = row.variants
    .map(parseVariant)
    .filter((variant): variant is RunVariantMeta => variant !== null);
  const batchId =
    typeof row.batchId === "string" && BATCH_ID_PATTERN.test(row.batchId)
      ? row.batchId
      : undefined;
  return {
    source: row.source,
    input: row.input,
    presetId: typeof row.presetId === "string" ? row.presetId : "",
    startedAt: row.startedAt,
    variants,
    ...(batchId ? { batchId } : {}),
    ...(typeof row.notice === "string" && row.notice ? { notice: row.notice } : {}),
  };
}

export async function saveRun(meta: RunMeta): Promise<void> {
  const jobIds = meta.variants.map((variant) => variant.jobId);
  try {
    await AsyncStorage.setItem(RUN_PREFIX + runKey(jobIds), JSON.stringify(meta));
    if (meta.batchId) {
      await Promise.all(
        jobIds.map((jobId) => AsyncStorage.setItem(JOB_BATCH_PREFIX + jobId, meta.batchId ?? "")),
      );
    }
  } catch {
    // Storage full or unavailable: the results screen still works from the route.
  }
}

export async function loadRun(jobIds: readonly string[]): Promise<RunMeta | null> {
  try {
    return parseRunMeta(await AsyncStorage.getItem(RUN_PREFIX + runKey(jobIds)));
  } catch {
    return null;
  }
}

export async function savePick(jobIds: readonly string[], picked: string): Promise<void> {
  try {
    await AsyncStorage.setItem(PICK_PREFIX + runKey(jobIds), picked);
  } catch {
    // Non-fatal: the pick simply is not remembered across launches.
  }
}

export async function loadPick(jobIds: readonly string[]): Promise<string> {
  try {
    const value = (await AsyncStorage.getItem(PICK_PREFIX + runKey(jobIds))) ?? "";
    return jobIds.includes(value) ? value : "";
  } catch {
    return "";
  }
}

/**
 * The winner-loop batch a job belongs to, when it was started from the
 * one-flow on this device ("" otherwise). Lets a reel's detail screen link
 * straight to its loop.
 */
export async function loadBatchForJob(jobId: string): Promise<string> {
  try {
    const value = (await AsyncStorage.getItem(JOB_BATCH_PREFIX + jobId)) ?? "";
    return BATCH_ID_PATTERN.test(value) ? value : "";
  } catch {
    return "";
  }
}
