"use client";

import * as React from "react";
import { AlertCircle, Loader2, Plus } from "lucide-react";
import type {
  CreatedWebhookSubscription,
  WebhookSubscribeRequest,
} from "@/lib/types";
import { WEBHOOK_EVENT_TYPES } from "@/lib/types";
import { ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface CreateWebhookFormProps {
  /** Register a subscription; resolves to the one-time secret reveal. */
  onCreate: (
    body: WebhookSubscribeRequest,
  ) => Promise<CreatedWebhookSubscription>;
  /** Called with the created subscription (including its one-time secret). */
  onCreated: (created: CreatedWebhookSubscription) => void;
  /** Disable the whole form (e.g. the caller lacks `workspace.settings`). */
  disabled?: boolean;
}

type Phase =
  | { status: "idle" }
  | { status: "creating" }
  | { status: "error"; message: string };

/** Toggle a value's membership in an immutable string set (returns a new array). */
function toggle(values: readonly string[], value: string): string[] {
  return values.includes(value)
    ? values.filter((v) => v !== value)
    : [...values, value];
}

/**
 * Form to register a webhook subscription: a callback `url` (must be https and is
 * SSRF-validated server-side) plus a non-empty selection of event types. On a
 * successful create the parent reveals the one-time signing secret; the fields
 * reset. All state is controlled and updated immutably.
 */
export function CreateWebhookForm({
  onCreate,
  onCreated,
  disabled = false,
}: CreateWebhookFormProps) {
  const [url, setUrl] = React.useState("");
  const [events, setEvents] = React.useState<readonly string[]>([]);
  const [phase, setPhase] = React.useState<Phase>({ status: "idle" });

  const busy = phase.status === "creating";
  const canSubmit =
    !busy && !disabled && url.trim().length > 0 && events.length > 0;

  const handleSubmit = React.useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (url.trim().length === 0 || events.length === 0) return;

      setPhase({ status: "creating" });
      try {
        const created = await onCreate({
          url: url.trim(),
          event_types: [...events],
        });
        onCreated(created);
        setUrl("");
        setEvents([]);
        setPhase({ status: "idle" });
      } catch (err) {
        const message =
          friendlyErrorMessage(err, "Couldn't create the subscription. Please try again.");
        setPhase({ status: "error", message });
      }
    },
    [events, onCreate, onCreated, url],
  );

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="webhook-url">Callback URL</Label>
        <Input
          id="webhook-url"
          type="url"
          inputMode="url"
          value={url}
          placeholder="https://yourapp.com/webhooks/menivor"
          onChange={(e) => setUrl(e.target.value)}
          disabled={busy || disabled}
          required
          autoComplete="off"
        />
        <p className="text-xs text-muted-foreground">
          Must be a public HTTPS endpoint. Internal, private, and loopback
          addresses are rejected.
        </p>
      </div>

      <fieldset
        className="space-y-2"
        disabled={busy || disabled}
        aria-describedby="webhook-events-help"
      >
        <legend className="text-sm font-medium">Events</legend>
        <p id="webhook-events-help" className="text-xs text-muted-foreground">
          Choose at least one event to receive.
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {WEBHOOK_EVENT_TYPES.map((evt) => {
            const checked = events.includes(evt);
            return (
              <label
                key={evt}
                className="flex cursor-pointer items-center gap-2 rounded-md border border-border bg-secondary/20 px-3 py-2 text-sm has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring"
              >
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  checked={checked}
                  onChange={() => setEvents((prev) => toggle(prev, evt))}
                  disabled={busy || disabled}
                />
                <code className="font-mono text-xs">{evt}</code>
              </label>
            );
          })}
        </div>
      </fieldset>

      {phase.status === "error" && (
        <p
          role="alert"
          className="flex items-center gap-2 text-sm text-destructive"
        >
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          {phase.message}
        </p>
      )}

      <Button type="submit" disabled={!canSubmit} className="w-full">
        {busy ? (
          <>
            <Loader2 className="animate-spin" /> Creating subscription…
          </>
        ) : (
          <>
            <Plus /> Create subscription
          </>
        )}
      </Button>
    </form>
  );
}
