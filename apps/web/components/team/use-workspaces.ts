"use client";

import * as React from "react";
import { ApiError, createWorkspace, listMyWorkspaces } from "@/lib/api";
import type { Workspace } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type WorkspacesStatus = "loading" | "ready" | "error";

export interface UseWorkspacesResult {
  status: WorkspacesStatus;
  workspaces: readonly Workspace[];
  errorMessage: string;
  /** True while a create request is in flight. */
  creating: boolean;
  /** Re-fetch the caller's workspaces. */
  reload: () => void;
  /**
   * Create a workspace and prepend it to the list. Returns the created
   * workspace on success (so the caller can auto-select it), or null on error.
   */
  create: (name: string) => Promise<Workspace | null>;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Owns the caller's workspace list (GET /workspaces) plus a `create` mutator
 * (POST /workspaces). State is only ever replaced, never mutated in place.
 */
export function useWorkspaces(): UseWorkspacesResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<WorkspacesStatus>("loading");
  const [workspaces, setWorkspaces] = React.useState<readonly Workspace[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [creating, setCreating] = React.useState(false);

  const mountedRef = React.useRef(true);
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const reload = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = await getApiToken();
      const result = await listMyWorkspaces({ token });
      if (!mountedRef.current) return;
      setWorkspaces(result);
      setStatus("ready");
    } catch (err) {
      if (!mountedRef.current) return;
      setErrorMessage(
        messageFor(err, "Couldn't load your workspaces. Please try again."),
      );
      setStatus("error");
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const create = React.useCallback(
    async (name: string): Promise<Workspace | null> => {
      setCreating(true);
      setErrorMessage("");
      try {
        const token = await getApiToken();
        const created = await createWorkspace(name, { token });
        if (mountedRef.current) {
          setWorkspaces((prev) => [
            created,
            ...prev.filter((w) => w.id !== created.id),
          ]);
          setStatus("ready");
        }
        return created;
      } catch (err) {
        if (mountedRef.current) {
          setErrorMessage(
            messageFor(err, "Couldn't create the workspace. Please try again."),
          );
        }
        return null;
      } finally {
        if (mountedRef.current) setCreating(false);
      }
    },
    [getApiToken],
  );

  return {
    status,
    workspaces,
    errorMessage,
    creating,
    reload: () => void reload(),
    create,
  };
}
