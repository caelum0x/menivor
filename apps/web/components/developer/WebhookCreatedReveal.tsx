"use client";

import * as React from "react";
import { ShieldAlert, Webhook, X } from "lucide-react";
import type { CreatedWebhookSubscription } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { CopyBox } from "@/components/apikeys/CopyBox";

interface WebhookCreatedRevealProps {
  /** The freshly created subscription, including its one-time signing secret. */
  created: CreatedWebhookSubscription;
  /** Dismiss the reveal (the caller has copied/stored the secret). */
  onDismiss: () => void;
}

/**
 * The ONE-TIME reveal of a newly created webhook subscription's HMAC signing
 * secret. Shows the full secret in a copy box with a prominent "you won't see it
 * again" warning. The secret exists only in this component's props (never
 * persisted client-side) and is gone once dismissed — the parent drops it from
 * state so it can never be re-rendered.
 */
export function WebhookCreatedReveal({
  created,
  onDismiss,
}: WebhookCreatedRevealProps) {
  return (
    <Card className="border-primary/40 bg-primary/5">
      <CardContent className="space-y-4 p-6">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
              <Webhook className="size-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="font-semibold">Webhook subscription created</p>
              <p className="truncate text-sm text-muted-foreground">
                Deliveries to{" "}
                <span className="font-medium">{created.url}</span> will be signed
                with this secret.
              </p>
            </div>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onDismiss}
            aria-label="Dismiss"
          >
            <X className="size-4" aria-hidden /> Done
          </Button>
        </div>

        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm"
        >
          <ShieldAlert
            className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400"
            aria-hidden
          />
          <p>
            Copy and store this signing secret now — you won&apos;t be able to
            see it again. We only keep an encrypted copy, so it can&apos;t be
            recovered. Use it to verify the{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">
              webhook-signature
            </code>{" "}
            header on each delivery (Standard Webhooks, with{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">
              webhook-id
            </code>{" "}
            and{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">
              webhook-timestamp
            </code>
            ; the body-only{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">
              X-Menivor-Signature
            </code>{" "}
            header is still sent but deprecated). If you lose it, delete this
            subscription and create a new one.
          </p>
        </div>

        <CopyBox value={created.secret} label="Copy webhook signing secret" />
      </CardContent>
    </Card>
  );
}
