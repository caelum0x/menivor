"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";

import { ApiError } from "@/src/shared/api";
import {
  checkout as checkoutRequest,
  createWalletDestination,
  createTransferChallenge,
  deleteTransferRecipient,
  getBalance,
  getWalletDestinationBalance,
  getWalletDestinations,
  getReceiveAddress,
  getSavedRecipients,
  getSourceBalance,
  getWalletSources,
  getWalletTransfer,
  newIdempotencyKey,
  saveTransferRecipient,
  setWalletDestinationActive,
  sendWalletTransfer,
  type CheckoutBody,
  type CheckoutResult,
  type WalletDestinationBalance,
  type WalletDestinationProfile,
  type WalletDestinationProfileRequest,
  type WalletBalance,
  type WalletReceiveAddress,
  type WalletSavedRecipient,
  type WalletSource,
  type WalletTransferChallenge,
  type WalletTransferChallengeRequest,
  type WalletTransferRequest,
  type WalletTransferResult,
} from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface UseWalletResult {
  balance: WalletBalance | null;
  loading: boolean;
  error: string;
  /** Re-fetch the balance (e.g. after a webhook-granted top-up settles). */
  refresh: () => Promise<void>;
  /** Start a top-up checkout (idempotent). Returns the intent + checkout URL. */
  checkout: (body: CheckoutBody) => Promise<CheckoutResult>;
  submitting: boolean;
  checkoutError: string;
  sources: WalletSource[];
  sourcesLoading: boolean;
  refreshSources: () => Promise<WalletSource[]>;
  loadSourceBalance: (sourceAccountId: string) => Promise<WalletBalance>;
  loadReceiveAddress: (sourceAccountId: string) => Promise<WalletReceiveAddress>;
  reviewTransfer: (
    body: WalletTransferChallengeRequest,
    idempotencyKey: string,
  ) => Promise<WalletTransferChallenge>;
  listSavedRecipients: (sourceAccountId: string) => Promise<WalletSavedRecipient[]>;
  saveRecipient: (sourceAccountId: string, handle: string) => Promise<WalletSavedRecipient>;
  deleteRecipient: (sourceAccountId: string, savedRecipientId: string) => Promise<void>;
  send: (body: WalletTransferRequest, idempotencyKey: string) => Promise<WalletTransferResult>;
  sending: boolean;
  recoverTransfer: (transferId: string) => Promise<WalletTransferResult>;
  recoveringTransfer: boolean;
  transferError: string;
  destinations: WalletDestinationProfile[];
  destinationsLoading: boolean;
  refreshDestinations: () => Promise<WalletDestinationProfile[]>;
  createDestination: (body: WalletDestinationProfileRequest) => Promise<WalletDestinationProfile>;
  setDestinationActive: (destinationId: string, active: boolean) => Promise<WalletDestinationProfile>;
  loadDestinationBalance: (destinationId: string) => Promise<WalletDestinationBalance>;
}

function messageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError || err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Live wallet state: fetches the balance on mount and exposes `refresh()` plus a
 * `checkout()` mutation. A checkout only creates a payment intent (credit is
 * granted asynchronously by the payment webhook), so the caller redirects the
 * user to the returned `checkout_url` and re-checks the balance later.
 */
export function useWallet(): UseWalletResult {
  const { getToken, isLoaded } = useAuth();
  const [balance, setBalance] = React.useState<WalletBalance | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [checkoutError, setCheckoutError] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [recoveringTransfer, setRecoveringTransfer] = React.useState(false);
  const [transferError, setTransferError] = React.useState("");
  const [sources, setSources] = React.useState<WalletSource[]>([]);
  const [sourcesLoading, setSourcesLoading] = React.useState(true);
  const [destinations, setDestinations] = React.useState<WalletDestinationProfile[]>([]);
  const [destinationsLoading, setDestinationsLoading] = React.useState(true);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      setBalance(await getBalance({ token }));
    } catch (err) {
      setError(messageOf(err, "Failed to load your wallet."));
      setBalance(null);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  const checkout = React.useCallback(
    async (body: CheckoutBody): Promise<CheckoutResult> => {
      setSubmitting(true);
      setCheckoutError("");
      try {
        const token = (await getToken()) ?? undefined;
        return await checkoutRequest(body, {
          token,
          idempotencyKey: newIdempotencyKey(),
        });
      } catch (err) {
        const message = messageOf(err, "Top-up failed. Please try again.");
        setCheckoutError(message);
        throw err;
      } finally {
        setSubmitting(false);
      }
    },
    [getToken],
  );

  const refreshSources = React.useCallback(async (): Promise<WalletSource[]> => {
    setSourcesLoading(true);
    try {
      const token = (await getToken()) ?? undefined;
      const next = await getWalletSources({ token });
      setSources(next);
      return next;
    } catch {
      setSources([]);
      return [];
    } finally {
      setSourcesLoading(false);
    }
  }, [getToken]);

  const loadSourceBalance = React.useCallback(async (sourceAccountId: string) => {
    const token = (await getToken()) ?? undefined;
    return getSourceBalance(sourceAccountId, { token });
  }, [getToken]);

  const loadReceiveAddress = React.useCallback(async (sourceAccountId: string) => {
    const token = (await getToken()) ?? undefined;
    return getReceiveAddress(sourceAccountId, { token });
  }, [getToken]);

  const refreshDestinations = React.useCallback(async () => {
    setDestinationsLoading(true);
    try {
      const token = (await getToken()) ?? undefined;
      const next = await getWalletDestinations({ token });
      setDestinations(next);
      return next;
    } catch {
      setDestinations([]);
      return [];
    } finally {
      setDestinationsLoading(false);
    }
  }, [getToken]);

  const createDestination = React.useCallback(async (
    body: WalletDestinationProfileRequest,
  ) => {
    const token = (await getToken()) ?? undefined;
    const created = await createWalletDestination(body, { token });
    setDestinations((current) => [...current, created]);
    return created;
  }, [getToken]);

  const setDestinationActive = React.useCallback(async (
    destinationId: string,
    active: boolean,
  ) => {
    const token = (await getToken()) ?? undefined;
    const updated = await setWalletDestinationActive(destinationId, active, { token });
    setDestinations((current) => current.map((item) =>
      item.destination_id === updated.destination_id ? updated : item
    ));
    return updated;
  }, [getToken]);

  const loadDestinationBalance = React.useCallback(async (destinationId: string) => {
    const token = (await getToken()) ?? undefined;
    return getWalletDestinationBalance(destinationId, { token });
  }, [getToken]);

  const reviewTransfer = React.useCallback(async (
    body: WalletTransferChallengeRequest,
    idempotencyKey: string,
  ) => {
    const token = (await getToken()) ?? undefined;
    return createTransferChallenge(body, idempotencyKey, { token });
  }, [getToken]);

  const listSavedRecipients = React.useCallback(async (sourceAccountId: string) => {
    const token = (await getToken()) ?? undefined;
    return getSavedRecipients(sourceAccountId, { token });
  }, [getToken]);

  const saveRecipient = React.useCallback(async (sourceAccountId: string, handle: string) => {
    const token = (await getToken()) ?? undefined;
    return saveTransferRecipient(sourceAccountId, handle, "", { token });
  }, [getToken]);

  const deleteRecipient = React.useCallback(async (sourceAccountId: string, savedRecipientId: string) => {
    const token = (await getToken()) ?? undefined;
    await deleteTransferRecipient(sourceAccountId, savedRecipientId, { token });
  }, [getToken]);

  const send = React.useCallback(
    async (
      body: WalletTransferRequest,
      idempotencyKey: string,
    ): Promise<WalletTransferResult> => {
      setSending(true);
      setTransferError("");
      try {
        const token = (await getToken()) ?? undefined;
        const result = await sendWalletTransfer(
          body,
          idempotencyKey,
          { token },
        );
        await refresh();
        return result;
      } catch (err) {
        setTransferError(
          err instanceof ApiError && err.status === 0
            ? "Transfer outcome is unknown. Confirm send again to reuse the same transfer key, or recover it by transfer ID."
            : messageOf(err, "Transfer failed. Please try again."),
        );
        throw err;
      } finally {
        setSending(false);
      }
    },
    [getToken, refresh],
  );

  const recoverTransfer = React.useCallback(
    async (transferId: string): Promise<WalletTransferResult> => {
      setRecoveringTransfer(true);
      setTransferError("");
      try {
        const token = (await getToken()) ?? undefined;
        const result = await getWalletTransfer(transferId, { token });
        await refresh();
        return result;
      } catch (err) {
        setTransferError(messageOf(err, "Could not recover that transfer."));
        throw err;
      } finally {
        setRecoveringTransfer(false);
      }
    },
    [getToken, refresh],
  );

  React.useEffect(() => {
    if (isLoaded) {
      void refresh();
      void refreshSources();
      void refreshDestinations();
    }
  }, [isLoaded, refresh, refreshDestinations, refreshSources]);

  return {
    balance,
    loading,
    error,
    refresh,
    checkout,
    submitting,
    checkoutError,
    sources,
    sourcesLoading,
    refreshSources,
    loadSourceBalance,
    loadReceiveAddress,
    reviewTransfer,
    listSavedRecipients,
    saveRecipient,
    deleteRecipient,
    send,
    sending,
    recoverTransfer,
    recoveringTransfer,
    transferError,
    destinations,
    destinationsLoading,
    refreshDestinations,
    createDestination,
    setDestinationActive,
    loadDestinationBalance,
  };
}
