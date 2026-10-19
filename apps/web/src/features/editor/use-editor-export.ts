"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { ApiError, createEditorExport } from "@/lib/api";
import type { CutRange } from "./model";
import { useEditorJob } from "./use-editor-job";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface PendingCommand {
  signature: string;
  idempotencyKey: string;
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `editor-${crypto.randomUUID()}`;
  }
  return `editor-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return friendlyErrorMessage(error);
  return "The selected cut could not be queued.";
}

export function useEditorExport(sourceJobId: string) {
  const { getToken } = useAuth();
  const [exportJobId, setExportJobId] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState("");
  const pending = React.useRef<PendingCommand | null>(null);
  const exportJob = useEditorJob(exportJobId);

  const submit = React.useCallback(async (cut: CutRange) => {
    const signature = JSON.stringify({
      sourceJobId,
      inPoint: Number(cut.inPoint.toFixed(3)),
      outPoint: Number(cut.outPoint.toFixed(3)),
    });
    if (!pending.current || pending.current.signature !== signature) {
      pending.current = { signature, idempotencyKey: newIdempotencyKey() };
    }

    setSubmitting(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      const created = await createEditorExport(
        sourceJobId,
        { in_point: cut.inPoint, out_point: cut.outPoint },
        { token, idempotencyKey: pending.current.idempotencyKey },
      );
      setExportJobId(created.job_id);
      pending.current = null;
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  }, [getToken, sourceJobId]);

  React.useEffect(() => {
    setExportJobId("");
    setError("");
    pending.current = null;
  }, [sourceJobId]);

  return { error, exportJob, exportJobId, submit, submitting };
}
