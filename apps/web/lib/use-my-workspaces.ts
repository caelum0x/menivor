"use client";

import * as React from "react";
import { ApiError, listMyWorkspaces } from "@/lib/api";
import type { Workspace } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type MyWorkspacesStatus = "loading" | "ready" | "error";

export interface UseMyWorkspacesResult {
  status: MyWorkspacesStatus;
  workspaces: readonly Workspace[];
  errorMessage: string;
  /** Re-fetch the caller's workspaces. */
  reload: () => void;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Read-only view of the caller's workspaces (GET /workspaces). Unlike the
 * team page's `useWorkspaces` (which also owns a create mutator), this is a
 * lightweight loader reusable by any surface that only needs the list — e.g.
 * the wizard's "Charge to" selector and the preset "Share to team" picker.
 * State is replaced, never mutated in place.
 */
export function useMyWorkspaces(): UseMyWorkspacesResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<MyWorkspacesStatus>("loading");
  const [workspaces, setWorkspaces] = React.useState<readonly Workspace[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");

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

  return {
    status,
    workspaces,
    errorMessage,
    reload: () => void reload(),
  };
}
