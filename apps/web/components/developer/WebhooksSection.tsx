"use client";

import * as React from "react";
import { RefreshCw, Webhook } from "lucide-react";
import type { CreatedWebhookSubscription } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CreateWebhookForm } from "@/components/developer/CreateWebhookForm";
import { WebhookCreatedReveal } from "@/components/developer/WebhookCreatedReveal";
import { WebhookSubscriptionCard } from "@/components/developer/WebhookSubscriptionCard";
import { useWebhookSubscriptions } from "@/lib/use-webhook-subscriptions";

interface WebhooksSectionProps {
  workspaceId: string | null;
  /** Whether the caller holds `workspace.settings` for this workspace. */
  canManage: boolean;
}

/**
 * The webhook-subscriptions surface for a single workspace: a create form (URL +
 * event types), the one-time signing-secret reveal, and the workspace's
 * subscriptions with per-subscription test + revoke + recent deliveries. All
 * management is gated by `workspace.settings` (owner/admin); a caller without it
 * sees a read-only "ask an admin" state. The signing secret is shown ONCE at
 * creation and never rendered again.
 */
export function WebhooksSection({
  workspaceId,
  canManage,
}: WebhooksSectionProps) {
  const { status, subscriptions, errorMessage, errorStatus, create, revoke, reload } =
    useWebhookSubscriptions(canManage ? workspaceId : null);
  const [revealed, setRevealed] =
    React.useState<CreatedWebhookSubscription | null>(null);

  const handleCreated = React.useCallback(
    (created: CreatedWebhookSubscription) => setRevealed(created),
    [],
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Webhook className="size-5 text-primary" aria-hidden />
              Webhooks
            </CardTitle>
            <CardDescription>
              Get a signed HTTP callback when jobs finish, publishes resolve, or
              performance is ingested. Each delivery is HMAC-signed and retried
              with backoff.
            </CardDescription>
          </div>
          {canManage && (
            <Button
              variant="outline"
              size="sm"
              onClick={reload}
              disabled={status === "loading"}
            >
              <RefreshCw
                className={
                  status === "loading" ? "size-4 animate-spin" : "size-4"
                }
                aria-hidden
              />
              Refresh
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {!canManage ? (
          <p className="rounded-md border border-border bg-secondary/30 p-4 text-sm text-muted-foreground">
            You need the workspace <strong>admin</strong> or{" "}
            <strong>owner</strong> role to manage webhook subscriptions. Ask a
            workspace admin for access.
          </p>
        ) : (
          <>
            <CreateWebhookForm
              onCreate={create}
              onCreated={handleCreated}
              disabled={status === "loading"}
            />

            {revealed && (
              <WebhookCreatedReveal
                created={revealed}
                onDismiss={() => setRevealed(null)}
              />
            )}

            <div className="space-y-3">
              <h3 className="text-sm font-semibold">
                Subscriptions
                {status === "ready" && subscriptions.length > 0 && (
                  <span className="ml-2 font-normal text-muted-foreground">
                    {subscriptions.length}
                  </span>
                )}
              </h3>

              {status === "loading" ? (
                <div className="space-y-3">
                  <Skeleton className="h-24 w-full rounded-lg" />
                  <Skeleton className="h-24 w-full rounded-lg" />
                </div>
              ) : status === "error" ? (
                <p
                  className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive"
                  role="alert"
                >
                  {errorStatus === 403
                    ? "You don't have permission to view this workspace's webhook subscriptions."
                    : errorMessage}
                </p>
              ) : subscriptions.length === 0 ? (
                <p className="rounded-md border border-dashed border-border p-4 text-center text-sm text-muted-foreground">
                  No subscriptions yet. Create one above to start receiving
                  signed events.
                </p>
              ) : (
                <ul className="space-y-3">
                  {subscriptions.map((sub) => (
                    <li key={sub.id}>
                      <WebhookSubscriptionCard
                        subscription={sub}
                        canManage={canManage}
                        onRevoke={revoke}
                      />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
