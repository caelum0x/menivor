"use client";

import * as React from "react";
import {
  ApiError,
  createWorkspaceInvite,
  inviteToWorkspace,
  listWorkspaceInvites,
  revokeWorkspaceInvite,
  type InviteOutcome,
  type WorkspaceInvite,
} from "@/lib/api";
import type { AssignableWorkspaceRole } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type InvitesStatus = "idle" | "loading" | "ready" | "error";

export interface UseInvitesResult {
  status: InvitesStatus;
  invites: readonly WorkspaceInvite[];
  errorMessage: string;
  inviting: boolean;
  inviteError: string;
  /** The most recent invite link created in this session (shown once). */
  lastLink: WorkspaceInvite | null;
  pendingIds: ReadonlySet<string>;
  rowErrors: Readonly<Record<string, string>>;
  reload: () => void;
  /** Invite by email; resolves with the outcome, or null on error. */
  invite: (email: string, role: AssignableWorkspaceRole) => Promise<InviteOutcome | null>;
  /** Issue a fresh accept link for a pending invite (replaces the old one). */
  newLink: (invite: WorkspaceInvite) => Promise<void>;
  revoke: (invite: WorkspaceInvite) => Promise<void>;
  dismissLastLink: () => void;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError || err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Pending workspace invites (GET/POST/DELETE /workspaces/{id}/invites) plus
 * the invite-by-email action. Only enabled for owners/admins (`enabled`).
 * Accept tokens are returned once, at creation, so the newest link is kept
 * in `lastLink` for the admin to copy; older rows can mint a fresh link.
 */
export function useInvites(workspaceId: string, enabled: boolean): UseInvitesResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<InvitesStatus>(enabled ? "loading" : "idle");
  const [invites, setInvites] = React.useState<readonly WorkspaceInvite[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [inviting, setInviting] = React.useState(false);
  const [inviteError, setInviteError] = React.useState("");
  const [lastLink, setLastLink] = React.useState<WorkspaceInvite | null>(null);
  const [pendingIds, setPendingIds] = React.useState<ReadonlySet<string>>(new Set());
  const [rowErrors, setRowErrors] = React.useState<Readonly<Record<string, string>>>({});
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    if (!enabled) {
      setStatus("idle");
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const load = async (): Promise<void> => {
      setStatus("loading");
      setErrorMessage("");
      try {
        const token = await getApiToken();
        const rows = await listWorkspaceInvites(workspaceId, { token, signal: controller.signal });
        if (cancelled) return;
        setInvites(rows);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setErrorMessage(messageFor(err, "Couldn't load pending invites."));
        setStatus("error");
      }
    };
    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [enabled, getApiToken, workspaceId, nonce]);

  const reload = React.useCallback(() => setNonce((n) => n + 1), []);

  const upsert = React.useCallback((invite: WorkspaceInvite) => {
    setInvites((prev) => [
      invite,
      ...prev.filter((i) => i.id !== invite.id && i.email !== invite.email),
    ]);
  }, []);

  const setRowPending = React.useCallback((id: string, on: boolean) => {
    setPendingIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const clearRowError = React.useCallback((id: string) => {
    setRowErrors((prev) => {
      if (!(id in prev)) return prev;
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }, []);

  const invite = React.useCallback(
    async (email: string, role: AssignableWorkspaceRole): Promise<InviteOutcome | null> => {
      setInviting(true);
      setInviteError("");
      try {
        const token = await getApiToken();
        const outcome = await inviteToWorkspace(workspaceId, { email, role }, { token });
        if (outcome.kind === "pending") {
          upsert(outcome.invite);
          setLastLink(outcome.invite);
        }
        return outcome;
      } catch (err) {
        setInviteError(messageFor(err, "Couldn't send the invite."));
        return null;
      } finally {
        setInviting(false);
      }
    },
    [getApiToken, upsert, workspaceId],
  );

  const newLink = React.useCallback(
    async (row: WorkspaceInvite): Promise<void> => {
      clearRowError(row.id);
      setRowPending(row.id, true);
      try {
        const token = await getApiToken();
        const fresh = await createWorkspaceInvite(
          workspaceId,
          { email: row.email, role: row.role as AssignableWorkspaceRole },
          { token },
        );
        upsert(fresh);
        setLastLink(fresh);
      } catch (err) {
        setRowErrors((prev) => ({ ...prev, [row.id]: messageFor(err, "Couldn't create a new link.") }));
      } finally {
        setRowPending(row.id, false);
      }
    },
    [clearRowError, getApiToken, setRowPending, upsert, workspaceId],
  );

  const revoke = React.useCallback(
    async (row: WorkspaceInvite): Promise<void> => {
      clearRowError(row.id);
      setRowPending(row.id, true);
      try {
        const token = await getApiToken();
        await revokeWorkspaceInvite(workspaceId, row.id, { token });
        setInvites((prev) => prev.filter((i) => i.id !== row.id));
        setLastLink((prev) => (prev?.id === row.id ? null : prev));
      } catch (err) {
        setRowErrors((prev) => ({ ...prev, [row.id]: messageFor(err, "Couldn't revoke this invite.") }));
      } finally {
        setRowPending(row.id, false);
      }
    },
    [clearRowError, getApiToken, setRowPending, workspaceId],
  );

  const dismissLastLink = React.useCallback(() => setLastLink(null), []);

  return {
    status,
    invites,
    errorMessage,
    inviting,
    inviteError,
    lastLink,
    pendingIds,
    rowErrors,
    reload,
    invite,
    newLink,
    revoke,
    dismissLastLink,
  };
}
