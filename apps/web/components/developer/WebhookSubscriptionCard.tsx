"use client";

import * as React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
  Send,
  Trash2,
} from "lucide-react";
import type { WebhookDelivery, WebhookSubscription } from "@/lib/types";
import { ApiError, testWebhookSubscription } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useApiToken } from "@/lib/use-api-token";
import { WebhookDeliveriesList } from "@/components/developer/WebhookDeliveriesList";
import {
  deliveryStatusLabel,
  deliveryStatusVariant,
  formatDateTime,
} from "@/components/developer/format";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface WebhookSubscriptionCardProps {
  subscription: WebhookSubscription;
  /** Whether the caller may test/revoke (holds `workspace.settings`). */
  canManage: boolean;
  /** Revoke this subscription (parent removes it from the list on success). */
  onRevoke: (subscriptionId: string) => Promise<void>;
}

/**
 * One webhook subscription: its callback URL + subscribed events + status, a
 * "Send test" button (delivers a signed test event via the server-side
 * primitive), a revoke button, and an expandable list of recent deliveries. A
 * successful test bumps the deliveries refresh so the new attempt appears. Never
 * renders the signing secret (it is unavailable after creation).
 */
export function WebhookSubscriptionCard({
  subscription,
  canManage,
  onRevoke,
}: WebhookSubscriptionCardProps) {
  const getApiToken = useApiToken();
  const [expanded, setExpanded] = React.useState(false);
  const [refreshNonce, setRefreshNonce] = React.useState(0);
  const [testing, setTesting] = React.useState(false);
  const [revoking, setRevoking] = React.useState(false);
  const [actionError, setActionError] = React.useState("");
  const [lastTest, setLastTest] = React.useState<WebhookDelivery | null>(null);

  const handleTest = React.useCallback(async () => {
    if (testing) return;
    setTesting(true);
    setActionError("");
    setLastTest(null);
    try {
      const token = await getApiToken();
      const delivery = await testWebhookSubscription(
        subscription.workspace_id,
        subscription.id,
        { token },
      );
      setLastTest(delivery);
      setExpanded(true);
      setRefreshNonce((n) => n + 1);
    } catch (err) {
      setActionError(
        friendlyErrorMessage(err, "Couldn't send the test event. Please try again."),
      );
    } finally {
      setTesting(false);
    }
  }, [getApiToken, subscription.id, subscription.workspace_id, testing]);

  const handleRevoke = React.useCallback(async () => {
    if (revoking) return;
    setRevoking(true);
    setActionError("");
    try {
      await onRevoke(subscription.id);
      // On success the parent removes this card; no local state to reset.
    } catch (err) {
      setActionError(
        friendlyErrorMessage(err, "Couldn't revoke the subscription. Please try again."),
      );
      setRevoking(false);
    }
  }, [onRevoke, revoking, subscription.id]);

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <div className="flex items-center gap-2">
              <code className="truncate font-mono text-sm">
                {subscription.url}
              </code>
              {subscription.enabled ? (
                <Badge variant="success">Active</Badge>
              ) : (
                <Badge variant="destructive">Disabled</Badge>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {subscription.event_types.map((evt) => (
                <Badge key={evt} variant="outline" className="font-mono">
                  {evt}
                </Badge>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              Created {formatDateTime(subscription.created_at)}
            </p>
          </div>

          {canManage && (
            <div className="flex shrink-0 gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleTest}
                disabled={testing || revoking}
              >
                {testing ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <Send className="size-4" aria-hidden />
                )}
                Test
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleRevoke}
                disabled={revoking || testing}
                className="text-destructive hover:text-destructive"
              >
                {revoking ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <Trash2 className="size-4" aria-hidden />
                )}
                Revoke
              </Button>
            </div>
          )}
        </div>

        {actionError && (
          <p
            className="flex items-center gap-2 text-sm text-destructive"
            role="alert"
          >
            <AlertTriangle className="size-4 shrink-0" aria-hidden />
            {actionError}
          </p>
        )}

        {lastTest && (
          <p className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-secondary/20 p-2 text-sm">
            <CheckCircle2
              className="size-4 shrink-0 text-muted-foreground"
              aria-hidden
            />
            Test event sent —{" "}
            <Badge variant={deliveryStatusVariant(lastTest.status)}>
              {deliveryStatusLabel(lastTest.status)}
            </Badge>
            {typeof lastTest.response_code === "number" ? (
              <span className="text-xs text-muted-foreground">
                HTTP {lastTest.response_code}
              </span>
            ) : null}
          </p>
        )}

        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          {expanded ? (
            <ChevronDown className="size-4" aria-hidden />
          ) : (
            <ChevronRight className="size-4" aria-hidden />
          )}
          Recent deliveries
        </button>

        {expanded && (
          <WebhookDeliveriesList
            workspaceId={subscription.workspace_id}
            subscriptionId={subscription.id}
            refreshNonce={refreshNonce}
          />
        )}
      </CardContent>
    </Card>
  );
}
