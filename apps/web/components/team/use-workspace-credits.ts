"use client";

import * as React from "react";
import { ApiError, getWorkspaceCredits, grantWorkspaceCredits } from "@/lib/api";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type WorkspaceCreditsStatus = "loading" | "ready" | "error";

export interface UseWorkspaceCreditsResult {
  status: WorkspaceCreditsStatus;
  /** Current SHARED pool balance, or null until first loaded. */
  balance: number | null;
  errorMessage: string;
  /** True while a grant request is in flight. */
  granting: boolean;
  /** Last grant error, cleared on the next attempt. */
  grantError: string;
  /** Re-fetch the pool balance. */
  reload: () => void;
  /**
   * Grant `amount` credits (optionally with a `reason`) to the pool, replacing
   * the balance with the server's updated value. Resolves true on success.
   */
  grant: (amount: number, reason?: string) => Promise<boolean>;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Owns one workspace's SHARED credit pool balance (GET /workspaces/{id}/credits)
 * plus an admin-only `grant` mutator (POST /workspaces/{id}/credits/grant). The
 * balance is only ever replaced with the server's authoritative value, never
 * mutated in place. Grant errors are surfaced separately so a failed top-up
 * never blanks the displayed balance.
 */
export function useWorkspaceCredits(
  workspaceId: string,
): UseWorkspaceCreditsResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<WorkspaceCreditsStatus>("loading");
  const [balance, setBalance] = React.useState<number | null>(null);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [granting, setGranting] = React.useState(false);
  const [grantError, setGrantError] = React.useState("");

  const mountedRef = React.useRef(true);
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const [reloadNonce, setReloadNonce] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const load = async (): Promise<void> => {
      setStatus("loading");
      setErrorMessage("");
      try {
        const token = await getApiToken();
        const result = await getWorkspaceCredits(workspaceId, {
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setBalance(result.balance);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setErrorMessage(
          messageFor(err, "Couldn't load the shared credit balance."),
        );
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

  const grant = React.useCallback(
    async (amount: number, reason?: string): Promise<boolean> => {
      setGranting(true);
      setGrantError("");
      try {
        const token = await getApiToken();
        const trimmedReason = reason?.trim();
        const result = await grantWorkspaceCredits(
          workspaceId,
          { amount, ...(trimmedReason ? { reason: trimmedReason } : {}) },
          { token },
        );
        if (mountedRef.current) {
          setBalance(result.balance);
          setStatus("ready");
        }
        return true;
      } catch (err) {
        if (mountedRef.current) {
          setGrantError(messageFor(err, "Couldn't grant credits."));
        }
        return false;
      } finally {
        if (mountedRef.current) setGranting(false);
      }
    },
    [getApiToken, workspaceId],
  );

  return {
    status,
    balance,
    errorMessage,
    granting,
    grantError,
    reload,
    grant,
  };
}
