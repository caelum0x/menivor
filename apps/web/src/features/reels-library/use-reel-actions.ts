"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { cancelJob, deleteJob, updateJob } from "@/lib/api";
import { friendlyErrorMessage } from "@/src/shared/errors";
import type { Job } from "@/lib/types";

export type ReelAction = "rename" | "archive" | "unarchive" | "cancel" | "delete";

export interface ReelActionHandlers {
  /** Job ids with a mutation in flight. */
  pendingIds: ReadonlySet<string>;
  /** Last error per job id (cleared on the next attempt for that job). */
  errors: Readonly<Record<string, string>>;
  rename: (job: Job, title: string) => Promise<boolean>;
  setArchived: (job: Job, archived: boolean) => Promise<boolean>;
  cancel: (job: Job) => Promise<boolean>;
  remove: (job: Job) => Promise<boolean>;
}

function messageOf(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

/**
 * Reel lifecycle mutations (PATCH / DELETE /jobs/{id}, POST /jobs/{id}/cancel)
 * with per-row pending + error state. `onUpdated` receives the server's fresh
 * job; `onRemoved` fires after a successful delete. The caller owns the list
 * and applies both immutably.
 */
export function useReelActions(
  onUpdated: (job: Job) => void,
  onRemoved: (jobId: string) => void,
): ReelActionHandlers {
  const { getToken } = useAuth();
  const [pendingIds, setPendingIds] = React.useState<ReadonlySet<string>>(new Set());
  const [errors, setErrors] = React.useState<Readonly<Record<string, string>>>({});

  const run = React.useCallback(
    async (jobId: string, fallback: string, action: (token?: string) => Promise<void>) => {
      setPendingIds((prev) => new Set(prev).add(jobId));
      setErrors((prev) => {
        if (!(jobId in prev)) return prev;
        const next = { ...prev };
        delete next[jobId];
        return next;
      });
      try {
        const token = (await getToken()) ?? undefined;
        await action(token);
        return true;
      } catch (err) {
        setErrors((prev) => ({ ...prev, [jobId]: messageOf(err, fallback) }));
        return false;
      } finally {
        setPendingIds((prev) => {
          const next = new Set(prev);
          next.delete(jobId);
          return next;
        });
      }
    },
    [getToken],
  );

  const rename = React.useCallback(
    (job: Job, title: string) =>
      run(job.job_id, "Couldn't rename this reel.", async (token) => {
        const trimmed = title.trim();
        const updated = await updateJob(job.job_id, { title: trimmed || null }, { token });
        onUpdated({ ...job, ...updated, title: updated.title ?? (trimmed || null) });
      }),
    [onUpdated, run],
  );

  const setArchived = React.useCallback(
    (job: Job, archived: boolean) =>
      run(
        job.job_id,
        archived ? "Couldn't archive this reel." : "Couldn't restore this reel.",
        async (token) => {
          const updated = await updateJob(job.job_id, { archived }, { token });
          onUpdated({ ...job, ...updated, archived: updated.archived ?? archived });
        },
      ),
    [onUpdated, run],
  );

  const cancel = React.useCallback(
    (job: Job) =>
      run(job.job_id, "Couldn't cancel this reel.", async (token) => {
        const updated = await cancelJob(job.job_id, { token });
        onUpdated({ ...job, ...updated });
      }),
    [onUpdated, run],
  );

  const remove = React.useCallback(
    (job: Job) =>
      run(job.job_id, "Couldn't delete this reel.", async (token) => {
        await deleteJob(job.job_id, { token });
        onRemoved(job.job_id);
      }),
    [onRemoved, run],
  );

  return { pendingIds, errors, rename, setArchived, cancel, remove };
}
