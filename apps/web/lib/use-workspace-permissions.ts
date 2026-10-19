"use client";

import * as React from "react";
import { ApiError, getMyPermissions } from "@/lib/api";
import type { Permission, Permissions, WorkspaceRole } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type PermissionsStatus = "idle" | "loading" | "ready" | "error";

export interface UseWorkspacePermissionsResult {
  status: PermissionsStatus;
  /** The caller's role in the workspace, or `null` for a non-member. */
  role: WorkspaceRole | null;
  /** The caller's effective permissions (empty for a non-member). */
  permissions: readonly Permission[];
  errorMessage: string;
  /** True when the caller holds `permission` in the selected workspace. */
  has: (permission: Permission) => boolean;
  reload: () => void;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Loads the caller's effective permissions for `workspaceId`
 * (GET /me/permissions). A blank id stays `idle` (nothing to load). The server
 * is always the source of truth — this is used only to drive UI affordances
 * (which controls to render). State is replaced, never mutated in place.
 */
export function useWorkspacePermissions(
  workspaceId: string | null,
): UseWorkspacePermissionsResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<PermissionsStatus>("idle");
  const [data, setData] = React.useState<Permissions | null>(null);
  const [errorMessage, setErrorMessage] = React.useState("");

  const [reloadNonce, setReloadNonce] = React.useState(0);
  const reload = React.useCallback(() => setReloadNonce((n) => n + 1), []);

  React.useEffect(() => {
    if (!workspaceId) {
      setStatus("idle");
      setData(null);
      setErrorMessage("");
      return;
    }
    let cancelled = false;
    const controller = new AbortController();

    void (async () => {
      setStatus("loading");
      setErrorMessage("");
      try {
        const token = await getApiToken();
        const result = await getMyPermissions(workspaceId, {
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setData(result);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setErrorMessage(messageFor(err, "Couldn't load your permissions."));
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, workspaceId, reloadNonce]);

  const permissions = React.useMemo<readonly Permission[]>(
    () => data?.permissions ?? [],
    [data],
  );
  const has = React.useCallback(
    (permission: Permission) => permissions.includes(permission),
    [permissions],
  );

  return {
    status,
    role: data?.role ?? null,
    permissions,
    errorMessage,
    has,
    reload,
  };
}
