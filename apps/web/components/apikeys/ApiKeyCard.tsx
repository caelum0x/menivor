"use client";

import * as React from "react";
import { KeyRound, Loader2, Trash2 } from "lucide-react";
import type { ApiKey } from "@/lib/types";
import { ApiError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { formatDate, formatLastUsed, isActive } from "@/components/apikeys/apikey-utils";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface ApiKeyCardProps {
  apiKey: ApiKey;
  /** Revoke by row id; resolves once the server confirms revocation. */
  onRevoke: (id: string) => Promise<void>;
}

/**
 * A single API key row: its label, non-secret prefix, created/last-used
 * metadata, and status, plus a confirm-guarded revoke for active keys. A revoked
 * key is shown greyed with no action (kept for the audit view).
 */
export function ApiKeyCard({ apiKey, onRevoke }: ApiKeyCardProps) {
  const [confirming, setConfirming] = React.useState(false);
  const [revoking, setRevoking] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const active = isActive(apiKey);
  const created = formatDate(apiKey.created_at);

  const handleRevoke = React.useCallback(async () => {
    setRevoking(true);
    setError(null);
    try {
      await onRevoke(apiKey.id);
      // On success the parent flips this key to revoked; reset local UI.
      setConfirming(false);
      setRevoking(false);
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Could not revoke this key. Please try again.");
      setError(message);
      setRevoking(false);
      setConfirming(false);
    }
  }, [apiKey.id, onRevoke]);

  return (
    <Card className={active ? undefined : "opacity-70"}>
      <CardContent className="space-y-3 p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
              <KeyRound className="size-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{apiKey.name}</p>
              <p className="truncate font-mono text-xs text-muted-foreground">
                {apiKey.prefix}…
              </p>
            </div>
          </div>
          <Badge variant={active ? "success" : "secondary"}>
            {active ? "Active" : "Revoked"}
          </Badge>
        </div>

        <dl className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
          <div>
            <dt className="font-medium text-foreground">Last used</dt>
            <dd>{formatLastUsed(apiKey.last_used_at)}</dd>
          </div>
          {created && (
            <div>
              <dt className="font-medium text-foreground">Created</dt>
              <dd>{created}</dd>
            </div>
          )}
        </dl>

        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        {active &&
          (confirming ? (
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="destructive"
                size="sm"
                onClick={handleRevoke}
                disabled={revoking}
              >
                {revoking ? (
                  <>
                    <Loader2 className="animate-spin" /> Revoking…
                  </>
                ) : (
                  <>
                    <Trash2 /> Confirm revoke
                  </>
                )}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setConfirming(false)}
                disabled={revoking}
              >
                Cancel
              </Button>
            </div>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setConfirming(true)}
              className="text-destructive hover:text-destructive"
            >
              <Trash2 /> Revoke
            </Button>
          ))}
      </CardContent>
    </Card>
  );
}
