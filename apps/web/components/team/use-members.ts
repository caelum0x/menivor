"use client";

import * as React from "react";
import {
  ApiError,
  inviteMember,
  leaveWorkspace,
  listMembers,
  removeMember,
  setMemberRole,
} from "@/lib/api";
import type {
  AssignableWorkspaceRole,
  Member,
  WorkspaceRole,
} from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type MembersStatus = "loading" | "ready" | "error";

export interface UseMembersResult {
  status: MembersStatus;
  members: readonly Member[];
  errorMessage: string;
  /** True while an invite request is in flight. */
  inviting: boolean;
  /** Last invite error, cleared on the next attempt. */
  inviteError: string;
  /** True while a leave request is in flight. */
  leaving: boolean;
  /** Last leave error, cleared on the next attempt. */
  leaveError: string;
  /** User ids currently being mutated (role change / removal), for spinners. */
  pendingIds: ReadonlySet<string>;
  /** Per-row error keyed by user id (role change / removal). */
  rowErrors: Readonly<Record<string, string>>;
  reload: () => void;
  /** Invite an existing user by email. Resolves true on success. */
  invite: (email: string, role?: AssignableWorkspaceRole) => Promise<boolean>;
  /** Change a member's role, updating the row on success. */
  changeRole: (userId: string, role: WorkspaceRole) => Promise<void>;
  /** Remove a member, dropping the row on success. */
  remove: (userId: string) => Promise<void>;
  /** Leave the workspace; invokes `onLeft` on success. */
  leave: () => Promise<void>;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Owns a single workspace's member list (GET /workspaces/{id}/members) plus the
 * invite / role-change / remove / leave mutators. All state is updated immutably
 * (never mutated in place); per-row pending + error state keeps controls
 * independent. `onLeft` fires after a successful leave so the parent can drop
 * the workspace from view.
 */
export function useMembers(
  workspaceId: string,
  onLeft?: () => void,
): UseMembersResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<MembersStatus>("loading");
  const [members, setMembers] = React.useState<readonly Member[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [inviting, setInviting] = React.useState(false);
  const [inviteError, setInviteError] = React.useState("");
  const [leaving, setLeaving] = React.useState(false);
  const [leaveError, setLeaveError] = React.useState("");
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

  // `onLeft` is read through a ref so it never re-triggers the load effect.
  const onLeftRef = React.useRef(onLeft);
  React.useEffect(() => {
    onLeftRef.current = onLeft;
  }, [onLeft]);

  const [reloadNonce, setReloadNonce] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const load = async (): Promise<void> => {
      setStatus("loading");
      setErrorMessage("");
      try {
        const token = await getApiToken();
        const list = await listMembers(workspaceId, {
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
    };

    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, workspaceId, reloadNonce]);

  const reload = React.useCallback(() => {
    setReloadNonce((n) => n + 1);
  }, []);

  const markPending = React.useCallback((userId: string, on: boolean) => {
    setPendingIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(userId);
      else next.delete(userId);
      return next;
    });
  }, []);

  const clearRowError = React.useCallback((userId: string) => {
    setRowErrors((prev) => {
      if (!(userId in prev)) return prev;
      const next = { ...prev };
      delete next[userId];
      return next;
    });
  }, []);

  const invite = React.useCallback(
    async (
      email: string,
      role?: AssignableWorkspaceRole,
    ): Promise<boolean> => {
      setInviting(true);
      setInviteError("");
      try {
        const token = await getApiToken();
        const created = await inviteMember(
          workspaceId,
          { email, ...(role ? { role } : {}) },
          { token },
        );
        if (mountedRef.current) {
          setMembers((prev) => [
            ...prev.filter((m) => m.user_id !== created.user_id),
            created,
          ]);
        }
        return true;
      } catch (err) {
        if (mountedRef.current) {
          setInviteError(messageFor(err, "Couldn't send the invite."));
        }
        return false;
      } finally {
        if (mountedRef.current) setInviting(false);
      }
    },
    [getApiToken, workspaceId],
  );

  const changeRole = React.useCallback(
    async (userId: string, role: WorkspaceRole): Promise<void> => {
      clearRowError(userId);
      markPending(userId, true);
      try {
        const token = await getApiToken();
        const updated = await setMemberRole(workspaceId, userId, role, {
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
    [clearRowError, getApiToken, markPending, workspaceId],
  );

  const remove = React.useCallback(
    async (userId: string): Promise<void> => {
      clearRowError(userId);
      markPending(userId, true);
      try {
        const token = await getApiToken();
        await removeMember(workspaceId, userId, { token });
        if (!mountedRef.current) return;
        setMembers((prev) => prev.filter((m) => m.user_id !== userId));
      } catch (err) {
        if (!mountedRef.current) return;
        setRowErrors((prev) => ({
          ...prev,
          [userId]: messageFor(err, "Couldn't remove this member."),
        }));
      } finally {
        if (mountedRef.current) markPending(userId, false);
      }
    },
    [clearRowError, getApiToken, markPending, workspaceId],
  );

  const leave = React.useCallback(async (): Promise<void> => {
    setLeaving(true);
    setLeaveError("");
    try {
      const token = await getApiToken();
      await leaveWorkspace(workspaceId, { token });
      if (!mountedRef.current) return;
      onLeftRef.current?.();
    } catch (err) {
      if (!mountedRef.current) return;
      setLeaveError(messageFor(err, "Couldn't leave this workspace."));
    } finally {
      if (mountedRef.current) setLeaving(false);
    }
  }, [getApiToken, workspaceId]);

  return {
    status,
    members,
    errorMessage,
    inviting,
    inviteError,
    leaving,
    leaveError,
    pendingIds,
    rowErrors,
    reload,
    invite,
    changeRole,
    remove,
    leave,
  };
}
