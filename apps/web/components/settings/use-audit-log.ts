"use client";

import * as React from "react";
import { ApiError, listAuditLog } from "@/lib/api";
import type { AuditEntry } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** Fixed audit page size (backend clamps to `[1, 100]`). */
export const AUDIT_PAGE_SIZE = 25;

export type AuditStatus = "loading" | "ready" | "error";

export interface UseAuditLogResult {
  status: AuditStatus;
  entries: readonly AuditEntry[];
  errorMessage: string;
  /** HTTP status of the last error (e.g. 403 when the caller lacks audit.read). */
  errorStatus: number | null;
  page: number;
  /** True when the current page returned a full window (there may be more). */
  hasMore: boolean;
  next: () => void;
  prev: () => void;
  reload: () => void;
}

/**
 * Owns a single workspace's APPEND-ONLY audit trail with simple offset paging
 * (GET /me/workspaces/{id}/audit). Since the endpoint is append-only and returns
 * no total count, "has more" is inferred from a full page. Tenant-scoped by the
 * server; a caller lacking `audit.read` gets a 403 surfaced via `errorStatus`.
 */
export function useAuditLog(workspaceId: string | null): UseAuditLogResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<AuditStatus>("loading");
  const [entries, setEntries] = React.useState<readonly AuditEntry[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [errorStatus, setErrorStatus] = React.useState<number | null>(null);
  const [page, setPage] = React.useState(0);
  const [reloadNonce, setReloadNonce] = React.useState(0);

  // Reset to the first page whenever the workspace changes.
  React.useEffect(() => {
    setPage(0);
  }, [workspaceId]);

  React.useEffect(() => {
    if (!workspaceId) {
      setStatus("ready");
      setEntries([]);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();

    void (async () => {
      setStatus("loading");
      setErrorMessage("");
      setErrorStatus(null);
      try {
        const token = await getApiToken();
        const rows = await listAuditLog(
          workspaceId,
          { limit: AUDIT_PAGE_SIZE, offset: page * AUDIT_PAGE_SIZE },
          { token, signal: controller.signal },
        );
        if (cancelled) return;
        setEntries(rows);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (err instanceof ApiError) {
          setErrorMessage(friendlyErrorMessage(err));
          setErrorStatus(err.status);
        } else {
          setErrorMessage("Couldn't load the audit log.");
          setErrorStatus(null);
        }
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, workspaceId, page, reloadNonce]);

  const next = React.useCallback(() => setPage((p) => p + 1), []);
  const prev = React.useCallback(() => setPage((p) => Math.max(0, p - 1)), []);
  const reload = React.useCallback(() => setReloadNonce((n) => n + 1), []);

  return {
    status,
    entries,
    errorMessage,
    errorStatus,
    page,
    hasMore: entries.length === AUDIT_PAGE_SIZE,
    next,
    prev,
    reload,
  };
}
