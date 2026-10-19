"use client";

import * as React from "react";
import { useApiToken } from "@/lib/use-api-token";
import {
  accessErrorMessage,
  confirmCreemReturn,
  confirmDodoReturn,
  dodoReturnIds,
  isCreemReturn,
  isFailedDodoReturn,
  type CreemConfirmResult,
} from "./api";

export type CreemReturnState =
  | { readonly phase: "none" }
  | { readonly phase: "confirming" }
  | { readonly phase: "done"; readonly result: CreemConfirmResult }
  | { readonly phase: "pending"; readonly message: string }
  | { readonly phase: "failed"; readonly message: string };

/** Neutral alias used by new code. */
export type PaymentReturnState = CreemReturnState;

/** Query keys either provider appends to our return URL. */
const RETURN_PARAMS = [
  "checkout",
  "checkout_id",
  "order_id",
  "customer_id",
  "subscription_id",
  "product_id",
  "request_id",
  "signature",
  "provider",
  "payment_id",
  "status",
  "email",
  "license_key",
] as const;

export const PENDING_MESSAGE =
  "Your payment is processing. Credits arrive automatically in a minute; you can keep going.";

/** Dodo can mark a payment succeeded a few seconds after the redirect. */
const DODO_RETRY_DELAYS_MS: readonly number[] = [0, 1500, 3000, 5000, 8000];

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function stripReturnParams(): void {
  const url = new URL(window.location.href);
  for (const key of RETURN_PARAMS) url.searchParams.delete(key);
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

async function confirmDodoWithRetry(
  ids: Parameters<typeof confirmDodoReturn>[0],
  getToken: () => Promise<string | undefined>,
  delays: readonly number[],
): Promise<CreemConfirmResult | null> {
  for (const delay of delays) {
    if (delay > 0) await sleep(delay);
    const token = await getToken();
    const result = await confirmDodoReturn(ids, { token });
    if (!result.pending) return result;
  }
  return null;
}

/**
 * When the page was opened by a checkout return (Creem's signed redirect, or a
 * Dodo Payments return carrying `payment_id` / `subscription_id`), credit the
 * payment once (the API is idempotent, so a refresh is harmless) and strip the
 * payment parameters from the address bar.
 */
export function useCreemReturn(
  { dodoRetryDelaysMs = DODO_RETRY_DELAYS_MS }: { dodoRetryDelaysMs?: readonly number[] } = {},
): CreemReturnState {
  const getToken = useApiToken();
  const [state, setState] = React.useState<CreemReturnState>({ phase: "none" });
  const started = React.useRef(false);

  React.useEffect(() => {
    if (started.current || typeof window === "undefined") return;
    const search = window.location.search;
    if (isFailedDodoReturn(search)) {
      started.current = true;
      stripReturnParams();
      setState({
        phase: "failed",
        message: "The payment did not go through, and you were not charged. Try again when you are ready.",
      });
      return;
    }
    const dodo = dodoReturnIds(search);
    const creem = !dodo && isCreemReturn(search);
    if (!dodo && !creem) return;
    started.current = true;
    setState({ phase: "confirming" });
    void (async () => {
      try {
        if (dodo) {
          const result = await confirmDodoWithRetry(dodo, getToken, dodoRetryDelaysMs);
          stripReturnParams();
          setState(result ? { phase: "done", result } : { phase: "pending", message: PENDING_MESSAGE });
          return;
        }
        const token = await getToken();
        const result = await confirmCreemReturn(search, { token });
        setState({ phase: "done", result });
        stripReturnParams();
      } catch (err) {
        setState({ phase: "failed", message: accessErrorMessage(err) });
      }
    })();
  }, [getToken, dodoRetryDelaysMs]);

  return state;
}

/** Neutral alias used by new code. */
export const usePaymentReturn = useCreemReturn;
