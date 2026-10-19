"use client";

import * as React from "react";
import { ApiError, getProviders } from "@/lib/api";
import { type PaymentProvider } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type PaymentProvidersStatus = "loading" | "ready" | "error";

export interface UsePaymentProvidersResult {
  status: PaymentProvidersStatus;
  /**
   * The ENABLED providers to offer at checkout, server-driven and in display
   * order. Empty until the first successful load (or when none are configured).
   */
  providers: readonly PaymentProvider[];
  errorMessage: string;
  /** Re-fetch the enabled providers. */
  reload: () => void;
}

function messageFor(err: unknown): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return "Couldn't load payment options.";
}

/**
 * Loads the payment providers the backend currently has enabled
 * (`GET /billing/providers`) so callers render only configured options. The
 * list is only ever replaced with the server's authoritative value, never
 * mutated in place; loading and error states are exposed for the UI to handle.
 */
export function usePaymentProviders(): UsePaymentProvidersResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<PaymentProvidersStatus>("loading");
  const [providers, setProviders] = React.useState<readonly PaymentProvider[]>(
    [],
  );
  const [errorMessage, setErrorMessage] = React.useState("");
  const [reloadNonce, setReloadNonce] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const load = async (): Promise<void> => {
      setStatus("loading");
      setErrorMessage("");
      try {
        const token = await getApiToken();
        const enabled = await getProviders({
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setProviders(enabled);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setErrorMessage(messageFor(err));
        setStatus("error");
      }
    };

    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, reloadNonce]);

  const reload = React.useCallback(() => {
    setReloadNonce((n) => n + 1);
  }, []);

  return { status, providers, errorMessage, reload };
}
