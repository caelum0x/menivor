/**
 * Active-workspace selection for the account/dev cluster.
 *
 * The app's workspace-scoped surfaces (subscription status, webhooks, shared
 * credits) all need to know WHICH workspace the caller is currently acting in.
 * There is no server-side "current workspace" concept — it is a purely client
 * preference — so we persist the chosen id locally with AsyncStorage (the same
 * store `lib/catalog.ts` and the Supabase session already use) and expose a
 * small hook that loads the caller's workspaces + resolves the active one.
 *
 * No secrets live here — the auth token is passed in by the calling screen and
 * flows through the shared `x-api-key` client. The stored value is only a
 * non-secret workspace id.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { useCallback, useEffect, useState } from "react";

import { isAbortError, listMyWorkspaces } from "./api";
import type { Workspace } from "./types";

const ACTIVE_WORKSPACE_KEY = "reelforge.activeWorkspaceId";

/** Reads the persisted active-workspace id, or `null` when none is stored. */
export async function loadActiveWorkspaceId(): Promise<string | null> {
  try {
    return await AsyncStorage.getItem(ACTIVE_WORKSPACE_KEY);
  } catch {
    return null;
  }
}

/** Persists the active-workspace id so it survives app restarts. */
export async function saveActiveWorkspaceId(id: string): Promise<void> {
  try {
    await AsyncStorage.setItem(ACTIVE_WORKSPACE_KEY, id);
  } catch {
    // A best-effort local preference — a storage failure is non-fatal.
  }
}

/** Clears the persisted active-workspace id (e.g. on sign-out). */
export async function clearActiveWorkspaceId(): Promise<void> {
  try {
    await AsyncStorage.removeItem(ACTIVE_WORKSPACE_KEY);
  } catch {
    // Non-fatal.
  }
}

export type ActiveWorkspaceStatus = "loading" | "ready" | "error";

export interface ActiveWorkspaceState {
  /** The caller's workspaces (any role), freshest fetch. */
  workspaces: readonly Workspace[];
  /** The resolved active workspace id, or `null` when the caller has none. */
  activeId: string | null;
  /** The resolved active workspace object, or `null`. */
  active: Workspace | null;
  status: ActiveWorkspaceStatus;
  error: string;
  /** Re-fetch the workspace list (keeps the current selection when still valid). */
  reload: () => void;
  /** Persist + switch the active workspace. */
  select: (id: string) => Promise<void>;
}

/**
 * Loads the caller's workspaces and resolves the persisted active selection.
 * Falls back to the first workspace when the stored id is stale/missing, and
 * persists that fallback so later reads are stable. The `token` is the caller's
 * API key (sent as `x-api-key`); the hook re-runs whenever it changes.
 */
export function useActiveWorkspace(
  token: string | undefined,
): ActiveWorkspaceState {
  const [workspaces, setWorkspaces] = useState<readonly Workspace[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [status, setStatus] = useState<ActiveWorkspaceStatus>("loading");
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  const select = useCallback(async (id: string): Promise<void> => {
    setActiveId(id);
    await saveActiveWorkspaceId(id);
  }, []);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setStatus("loading");
    setError("");

    (async () => {
      try {
        const [rows, storedId] = await Promise.all([
          listMyWorkspaces({ token, signal: controller.signal }),
          loadActiveWorkspaceId(),
        ]);
        if (!active) return;
        setWorkspaces(rows);

        const stillValid =
          storedId !== null && rows.some((w) => w.id === storedId);
        const resolved = stillValid ? storedId : rows[0]?.id ?? null;
        setActiveId(resolved);
        // Persist a fallback so the selection is stable across launches.
        if (resolved !== null && resolved !== storedId) {
          await saveActiveWorkspaceId(resolved);
        }
        setStatus("ready");
      } catch (err: unknown) {
        if (!active || isAbortError(err)) return;
        setError(
          err instanceof Error ? err.message : "Failed to load workspaces.",
        );
        setStatus("error");
      }
    })();

    return () => {
      active = false;
      controller.abort();
    };
  }, [token, nonce]);

  const activeWorkspace =
    workspaces.find((w) => w.id === activeId) ?? null;

  return {
    workspaces,
    activeId,
    active: activeWorkspace,
    status,
    error,
    reload,
    select,
  };
}
