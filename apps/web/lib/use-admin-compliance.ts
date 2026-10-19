"use client";

import * as React from "react";
import {
  ApiError,
  adminEraseUser,
  adminListErasureRequests,
  adminRetentionOverview,
} from "@/lib/api";
import type { ErasureRequest, RetentionPolicy } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type AdminComplianceStatus = "loading" | "ready" | "error";

export interface UseAdminComplianceResult {
  status: AdminComplianceStatus;
  /** Cross-tenant erasure requests (newest first). */
  requests: readonly ErasureRequest[];
  /** Every configured workspace retention policy (posture overview). */
  policies: readonly RetentionPolicy[];
  errorMessage: string;
  /**
   * Operator-initiated erasure of a TARGET user (staff-only, audited with the
   * operator as actor). On success the new completed request is prepended to the
   * listing. Anonymizes the target's PII while preserving financial/audit records.
   */
  eraseUser: (userId: string) => Promise<ErasureRequest>;
  reload: () => void;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Owns the PLATFORM-ADMIN compliance overview (GET /admin/erasure-requests +
 * /admin/retention) and the operator-initiated erasure action (POST
 * /admin/erasure/{id}). Every underlying endpoint is HARD-GATED on `is_staff`
 * server-side — a non-staff caller (incl. a workspace owner) gets a 403 and
 * never reaches the cross-tenant data. State is only ever replaced/prepended
 * immutably with the server's authoritative values.
 */
export function useAdminCompliance(): UseAdminComplianceResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<AdminComplianceStatus>("loading");
  const [requests, setRequests] = React.useState<readonly ErasureRequest[]>([]);
  const [policies, setPolicies] = React.useState<readonly RetentionPolicy[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [reloadNonce, setReloadNonce] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    void (async () => {
      setStatus("loading");
      setErrorMessage("");
      try {
        const token = await getApiToken();
        const [reqs, pols] = await Promise.all([
          adminListErasureRequests(
            { limit: 200 },
            { token, signal: controller.signal },
          ),
          adminRetentionOverview({ token, signal: controller.signal }),
        ]);
        if (cancelled) return;
        setRequests(reqs);
        setPolicies(pols);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setErrorMessage(messageFor(err, "Couldn't load the compliance overview."));
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, reloadNonce]);

  const eraseUser = React.useCallback(
    async (userId: string): Promise<ErasureRequest> => {
      const token = await getApiToken();
      const result = await adminEraseUser(userId, { token });
      setRequests((prev) => [result, ...prev]);
      return result;
    },
    [getApiToken],
  );

  const reload = React.useCallback(() => setReloadNonce((n) => n + 1), []);

  return { status, requests, policies, errorMessage, eraseUser, reload };
}
