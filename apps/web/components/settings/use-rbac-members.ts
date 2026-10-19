"use client";

import * as React from "react";
import { ApiError, listWorkspaceMembers, updateMemberRole } from "@/lib/api";
import type { Member, WorkspaceRole } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type RbacMembersStatus = "loading" | "ready" | "error";

export interface UseRbacMembersResult {
  status: RbacMembersStatus;
  members: readonly Member[];
  errorMessage: string;
  /** Number of members currently holding the `owner` role (for the last-owner guard). */
  ownerCount: number;
  /** User ids whose role change is in flight (for per-row spinners). */
  pendingIds: ReadonlySet<string>;
  /** Per-row error keyed by user id. */
  rowErrors: Readonly<Record<string, string>>;
  reload: () => void;
  /** Change a member's Enterprise role (PATCH .../members/{userId}/role). */
  changeRole: (userId: string, role: WorkspaceRole) => Promise<void>;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Owns a single workspace's Enterprise roster (GET /me/workspaces/{id}/members)
 * plus the role-change mutator (PATCH .../members/{userId}/role). All state is
 * replaced immutably; per-row pending + error state keeps rows independent. The
 * server enforces every rule (escalation + last-owner guards); this hook surfaces
 * whatever error the API returns on the affected row.
 */
export function useRbacMembers(workspaceId: string | null): UseRbacMembersResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<RbacMembersStatus>("loading");
  const [members, setMembers] = React.useState<readonly Member[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [pendingIds, setPendingIds] = React.useState<ReadonlySet<string>>(
    new Set(),
  );
  const [rowErrors, setRowErrors] = React.useState<
    Readonly<Record<string, string>>
  >({});

  const mountedRef = React.useRef(true);
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const [reloadNonce, setReloadNonce] = React.useState(0);
  const reload = React.useCallback(() => setReloadNonce((n) => n + 1), []);

  React.useEffect(() => {
    if (!workspaceId) {
      setStatus("ready");
      setMembers([]);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();

    void (async () => {
      setStatus("loading");
      setErrorMessage("");
      try {
        const token = await getApiToken();
        const list = await listWorkspaceMembers(workspaceId, {
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setMembers(list);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setErrorMessage(messageFor(err, "Couldn't load the member list."));
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, workspaceId, reloadNonce]);

  const markPending = React.useCallback((userId: string, on: boolean) => {
    setPendingIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(userId);
      else next.delete(userId);
      return next;
    });
  }, []);

  const changeRole = React.useCallback(
    async (userId: string, role: WorkspaceRole): Promise<void> => {
      if (!workspaceId) return;
      setRowErrors((prev) => {
        if (!(userId in prev)) return prev;
        const next = { ...prev };
        delete next[userId];
        return next;
      });
      markPending(userId, true);
      try {
        const token = await getApiToken();
        const updated = await updateMemberRole(workspaceId, userId, role, {
          token,
        });
        if (!mountedRef.current) return;
        setMembers((prev) =>
          prev.map((m) =>
            m.user_id === userId ? { ...m, role: updated.role } : m,
          ),
        );
      } catch (err) {
        if (!mountedRef.current) return;
        setRowErrors((prev) => ({
          ...prev,
          [userId]: messageFor(err, "Couldn't change this member's role."),
        }));
      } finally {
        if (mountedRef.current) markPending(userId, false);
      }
    },
    [getApiToken, markPending, workspaceId],
  );

  const ownerCount = React.useMemo(
    () => members.filter((m) => m.role === "owner").length,
    [members],
  );

  return {
    status,
    members,
    errorMessage,
    ownerCount,
    pendingIds,
    rowErrors,
    reload,
    changeRole,
  };
}
