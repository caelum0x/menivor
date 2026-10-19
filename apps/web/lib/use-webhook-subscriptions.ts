"use client";

import * as React from "react";
import {
  ApiError,
  createWebhookSubscription,
  deleteWebhookSubscription,
  listWebhookSubscriptions,
} from "@/lib/api";
import type {
  CreatedWebhookSubscription,
  WebhookSubscribeRequest,
  WebhookSubscription,
} from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

// Re-exported so the webhook fetchers are reachable alongside the hook (the
// section mutates through `create` / `revoke` below).
export { createWebhookSubscription, deleteWebhookSubscription };

export type WebhookSubscriptionsStatus = "idle" | "loading" | "ready" | "error";

export interface UseWebhookSubscriptionsResult {
  status: WebhookSubscriptionsStatus;
  /** The workspace's subscriptions (newest first; never carries a secret). */
  subscriptions: readonly WebhookSubscription[];
  errorMessage: string;
  /** HTTP status of the last load error (e.g. 403 when the caller lacks settings). */
  errorStatus: number | null;
  /**
   * Register a subscription. Resolves to the created subscription WITH its
   * one-time signing `secret` (shown once, then unrecoverable). The listing is
   * updated immediately with the secret-free descriptor.
   */
  create: (
    body: WebhookSubscribeRequest,
  ) => Promise<CreatedWebhookSubscription>;
  /** Revoke a subscription by id; drops it from the list on success. */
  revoke: (subscriptionId: string) => Promise<void>;
  /** Re-fetch the workspace's subscriptions. */
  reload: () => void;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/** Strip the one-time secret from a created subscription for list storage. */
function toListItem(created: CreatedWebhookSubscription): WebhookSubscription {
  // Destructure the secret away so it can NEVER be retained in list state.
  const { secret: _secret, ...rest } = created;
  void _secret;
  return rest;
}

/**
 * Owns a single workspace's webhook subscriptions
 * (GET/POST/DELETE /me/workspaces/{id}/webhooks). A created subscription's
 * signing secret is returned EXACTLY ONCE (the caller reveals it, then it is
 * unrecoverable); the list never carries a secret. Gated by `workspace.settings`
 * server-side; a caller lacking it surfaces via `errorStatus === 403`. State is
 * updated immutably — a revoked subscription is removed from the list.
 */
export function useWebhookSubscriptions(
  workspaceId: string | null,
): UseWebhookSubscriptionsResult {
  const getApiToken = useApiToken();
  const [status, setStatus] =
    React.useState<WebhookSubscriptionsStatus>("idle");
  const [subscriptions, setSubscriptions] = React.useState<
    readonly WebhookSubscription[]
  >([]);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [errorStatus, setErrorStatus] = React.useState<number | null>(null);
  const [reloadNonce, setReloadNonce] = React.useState(0);

  React.useEffect(() => {
    if (!workspaceId) {
      setStatus("idle");
      setSubscriptions([]);
      setErrorMessage("");
      setErrorStatus(null);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();

    void (async () => {
      setStatus("loading");
      setErrorMessage("");
      setErrorStatus(null);
      try {
        const token = await getApiToken();
        const result = await listWebhookSubscriptions(workspaceId, {
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setSubscriptions(result);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setErrorMessage(
          messageFor(err, "Couldn't load the webhook subscriptions."),
        );
        setErrorStatus(err instanceof ApiError ? err.status : null);
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, workspaceId, reloadNonce]);

  const create = React.useCallback(
    async (
      body: WebhookSubscribeRequest,
    ): Promise<CreatedWebhookSubscription> => {
      if (!workspaceId) throw new Error("No workspace selected.");
      const token = await getApiToken();
      const created = await createWebhookSubscription(workspaceId, body, {
        token,
      });
      // Reflect the new subscription in the list WITHOUT its one-time secret.
      const listItem = toListItem(created);
      setSubscriptions((prev) => [
        listItem,
        ...prev.filter((s) => s.id !== created.id),
      ]);
      setStatus("ready");
      return created;
    },
    [getApiToken, workspaceId],
  );

  const revoke = React.useCallback(
    async (subscriptionId: string): Promise<void> => {
      if (!workspaceId) throw new Error("No workspace selected.");
      const token = await getApiToken();
      await deleteWebhookSubscription(workspaceId, subscriptionId, { token });
      setSubscriptions((prev) => prev.filter((s) => s.id !== subscriptionId));
    },
    [getApiToken, workspaceId],
  );

  const reload = React.useCallback(() => setReloadNonce((n) => n + 1), []);

  return {
    status,
    subscriptions,
    errorMessage,
    errorStatus,
    create,
    revoke,
    reload,
  };
}
