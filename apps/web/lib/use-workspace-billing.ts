"use client";

import * as React from "react";
import {
  cancelWorkspaceSubscription,
  changeWorkspacePlan,
  getEntitlements,
  getSubscription,
  getWorkspaceUsage,
  listWorkspaceInvoices,
  subscribeWorkspace,
} from "@/lib/api";
import { readableApiError } from "@/src/shared/launch-gate/gate";
import type {
  Entitlements,
  Invoice,
  SubscribeRequest,
  SubscribeResult,
  Subscription,
  Usage,
} from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { currentPeriod } from "@/components/billing/format";

export type BillingStatus = "idle" | "loading" | "ready" | "error";

export interface UseWorkspaceBillingResult {
  status: BillingStatus;
  /** The workspace's active-plan entitlement bundle (membership read). */
  entitlements: Entitlements | null;
  /** Metered usage + overage for `period` (membership read). */
  usage: Usage | null;
  /** The live subscription, or `null` (only loaded when `canManage`). */
  subscription: Subscription | null;
  /** The workspace's invoices, newest first (only loaded when `canManage`). */
  invoices: readonly Invoice[];
  /** First read error, if any (a partial failure still shows what loaded). */
  errorMessage: string;
  /** The billing month being viewed (`'YYYY-MM'`). */
  period: string;
  setPeriod: (period: string) => void;
  /** True while a mutation (subscribe / change / cancel) is in flight. */
  pending: boolean;
  /** Last mutation error, cleared when a new mutation starts. */
  actionError: string;
  /** Start a recurring checkout (Stripe, Creem or Polar) — returns the hosted-checkout envelope. */
  subscribe: (body: SubscribeRequest) => Promise<SubscribeResult>;
  /** Switch the plan at the payment provider (prorated), then refresh. */
  changePlan: (planKey: string) => Promise<Subscription>;
  /** Cancel at the payment provider now (falls back to base/free), then refresh. */
  cancel: () => Promise<Subscription>;
  reload: () => void;
}

function messageFor(err: unknown, fallback: string): string {
  // No request ids in the UI; launch-gate refusals become the honest reason.
  return readableApiError(err, fallback);
}

function firstRejection(
  results: readonly PromiseSettledResult<unknown>[],
  fallback: string,
): string {
  const failed = results.find(
    (r): r is PromiseRejectedResult => r.status === "rejected",
  );
  return failed ? messageFor(failed.reason, fallback) : "";
}

/**
 * Loads a workspace's billing state and exposes the management mutators, with
 * RBAC honored client-side to mirror the server: entitlements + usage are
 * membership reads (any member), while the subscription + invoices are only
 * fetched when `canManage` (the `billing.manage` gate) — a viewer never triggers
 * a 403 for them. TENANT-SCOPED: every call is keyed to `workspaceId`, so no
 * other tenant's rows are ever requested. State is replaced, never mutated in
 * place; the server stays the source of truth (mutators refetch on success).
 */
export function useWorkspaceBilling(
  workspaceId: string | null,
  canManage: boolean,
): UseWorkspaceBillingResult {
  const getApiToken = useApiToken();

  const [status, setStatus] = React.useState<BillingStatus>("idle");
  const [entitlements, setEntitlements] = React.useState<Entitlements | null>(
    null,
  );
  const [usage, setUsage] = React.useState<Usage | null>(null);
  const [subscription, setSubscription] = React.useState<Subscription | null>(
    null,
  );
  const [invoices, setInvoices] = React.useState<readonly Invoice[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [period, setPeriod] = React.useState<string>(() => currentPeriod());

  const [pending, setPending] = React.useState(false);
  const [actionError, setActionError] = React.useState("");

  const [reloadNonce, setReloadNonce] = React.useState(0);
  const reload = React.useCallback(() => setReloadNonce((n) => n + 1), []);

  React.useEffect(() => {
    if (!workspaceId) {
      setStatus("idle");
      setEntitlements(null);
      setUsage(null);
      setSubscription(null);
      setInvoices([]);
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
        const opts = { token, signal: controller.signal };

        // Membership reads always run; management reads only when permitted.
        const [entResult, usageResult, subResult, invResult] =
          await Promise.allSettled([
            getEntitlements(workspaceId, opts),
            getWorkspaceUsage(workspaceId, period, opts),
            canManage
              ? getSubscription(workspaceId, opts)
              : Promise.resolve<Subscription | null>(null),
            canManage
              ? listWorkspaceInvoices(workspaceId, opts)
              : Promise.resolve<Invoice[]>([]),
          ]);

        if (cancelled) return;

        if (entResult.status === "fulfilled") setEntitlements(entResult.value);
        if (usageResult.status === "fulfilled") setUsage(usageResult.value);
        if (subResult.status === "fulfilled") setSubscription(subResult.value);
        if (invResult.status === "fulfilled") setInvoices(invResult.value);

        const problem = firstRejection(
          [entResult, usageResult, subResult, invResult],
          "Couldn't load billing details.",
        );
        setErrorMessage(problem);
        // Only a total failure (no read succeeded) is a hard error state.
        const anyOk =
          entResult.status === "fulfilled" ||
          usageResult.status === "fulfilled" ||
          subResult.status === "fulfilled" ||
          invResult.status === "fulfilled";
        setStatus(anyOk ? "ready" : "error");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setErrorMessage(messageFor(err, "Couldn't load billing details."));
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, workspaceId, canManage, period, reloadNonce]);

  const runMutation = React.useCallback(
    async <T,>(fn: (token: string | undefined) => Promise<T>): Promise<T> => {
      setPending(true);
      setActionError("");
      try {
        const token = await getApiToken();
        const result = await fn(token);
        reload();
        return result;
      } catch (err) {
        setActionError(messageFor(err, "Something went wrong. Please retry."));
        throw err;
      } finally {
        setPending(false);
      }
    },
    [getApiToken, reload],
  );

  const subscribe = React.useCallback(
    (body: SubscribeRequest) => {
      if (!workspaceId) return Promise.reject(new Error("No workspace selected"));
      return runMutation((token) => subscribeWorkspace(workspaceId, body, { token }));
    },
    [runMutation, workspaceId],
  );

  const changePlan = React.useCallback(
    (planKey: string) => {
      if (!workspaceId) return Promise.reject(new Error("No workspace selected"));
      return runMutation((token) =>
        changeWorkspacePlan(workspaceId, { plan_key: planKey }, { token }),
      );
    },
    [runMutation, workspaceId],
  );

  const cancel = React.useCallback(() => {
    if (!workspaceId) return Promise.reject(new Error("No workspace selected"));
    return runMutation((token) => cancelWorkspaceSubscription(workspaceId, { token }));
  }, [runMutation, workspaceId]);

  return {
    status,
    entitlements,
    usage,
    subscription,
    invoices,
    errorMessage,
    period,
    setPeriod,
    pending,
    actionError,
    subscribe,
    changePlan,
    cancel,
    reload,
  };
}
