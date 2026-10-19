"use client";

import * as React from "react";
import { ApiError, eraseMyAccount } from "@/lib/api";
import type { ErasureRequest } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type AccountErasureStatus = "idle" | "erasing" | "done" | "error";

export interface UseAccountErasureResult {
  status: AccountErasureStatus;
  /** The completed erasure request, once done. */
  request: ErasureRequest | null;
  errorMessage: string;
  /**
   * Irreversibly erase the CALLER'S OWN account. The server requires a
   * confirmation gate and only ever erases the resolved caller — no target id is
   * accepted. Resolves to the completed erasure request.
   */
  erase: () => Promise<ErasureRequest>;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Owns the caller's right-to-erasure action (POST /me/erase, GDPR Art. 17). The
 * action is STRICTLY caller-scoped — the server erases only the resolved caller
 * (no target id is accepted) and anonymizes PII in place while preserving
 * financial/audit records. Irreversible; the caller must present a deliberate
 * confirmation in the UI before this is invoked.
 */
export function useAccountErasure(): UseAccountErasureResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<AccountErasureStatus>("idle");
  const [request, setRequest] = React.useState<ErasureRequest | null>(null);
  const [errorMessage, setErrorMessage] = React.useState("");

  const erase = React.useCallback(async (): Promise<ErasureRequest> => {
    setStatus("erasing");
    setErrorMessage("");
    try {
      const token = await getApiToken();
      const result = await eraseMyAccount({ token });
      setRequest(result);
      setStatus("done");
      return result;
    } catch (err) {
      setErrorMessage(
        messageFor(err, "Couldn't erase your account. Please try again."),
      );
      setStatus("error");
      throw err;
    }
  }, [getApiToken]);

  return { status, request, errorMessage, erase };
}
