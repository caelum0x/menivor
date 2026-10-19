"use client";

import * as React from "react";
import {
  AlertTriangle,
  KeyRound,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import type { ScimToken } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CopyBox } from "@/components/apikeys/CopyBox";
import { ApiError } from "@/lib/api";
import type { ScimTokensStatus } from "@/lib/use-scim-tokens";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface ScimTokensSectionProps {
  status: ScimTokensStatus;
  tokens: readonly ScimToken[];
  errorMessage: string;
  /** True when the load error was a 403 (caller lacks `workspace.settings`). */
  forbidden: boolean;
  canManage: boolean;
  /** The IdP-facing SCIM 2.0 base URL for this workspace. */
  scimBaseUrl: string;
  onCreate: () => Promise<ScimToken>;
  onRevoke: (tokenId: string) => Promise<void>;
  onReload: () => void;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

/**
 * Manage a workspace's SCIM 2.0 provisioning tokens. Minting reveals the raw
 * bearer token EXACTLY ONCE (stored only as a digest server-side); the listing
 * never carries a secret. A token is scoped to this one workspace and can never
 * provision into another. Editing controls appear only when the caller holds
 * `workspace.settings`.
 */
export function ScimTokensSection({
  status,
  tokens,
  errorMessage,
  forbidden,
  canManage,
  scimBaseUrl,
  onCreate,
  onRevoke,
  onReload,
}: ScimTokensSectionProps) {
  const [revealed, setRevealed] = React.useState<ScimToken | null>(null);
  const [minting, setMinting] = React.useState(false);
  const [actionError, setActionError] = React.useState("");
  const [pendingId, setPendingId] = React.useState<string | null>(null);

  const handleCreate = React.useCallback(async () => {
    if (minting) return;
    setMinting(true);
    setActionError("");
    try {
      const created = await onCreate();
      setRevealed(created);
    } catch (err) {
      setActionError(
        friendlyErrorMessage(err, "Couldn't create a SCIM token. Please try again."),
      );
    } finally {
      setMinting(false);
    }
  }, [minting, onCreate]);

  const handleRevoke = React.useCallback(
    async (tokenId: string) => {
      setPendingId(tokenId);
      setActionError("");
      try {
        await onRevoke(tokenId);
      } catch (err) {
        setActionError(
          friendlyErrorMessage(err, "Couldn't revoke the token. Please try again."),
        );
      } finally {
        setPendingId(null);
      }
    },
    [onRevoke],
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>SCIM provisioning</CardTitle>
            <CardDescription>
              Mint a bearer token so your IdP can create, update, and deactivate
              members automatically via SCIM 2.0.
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={onReload}
            disabled={status === "loading"}
          >
            <RefreshCw
              className={status === "loading" ? "size-4 animate-spin" : "size-4"}
              aria-hidden
            />
            Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5 rounded-lg border border-border bg-secondary/20 p-4">
          <p className="text-xs font-medium text-muted-foreground">
            SCIM base URL
          </p>
          <CopyBox value={scimBaseUrl} label="Copy SCIM base URL" />
        </div>

        {forbidden ? (
          <p className="rounded-md border border-border bg-secondary/30 p-4 text-sm text-muted-foreground">
            You don&apos;t have permission to manage SCIM tokens for this
            workspace. Ask an admin or owner.
          </p>
        ) : status === "error" ? (
          <div className="flex items-center gap-2 text-sm text-destructive" role="alert">
            <AlertTriangle className="size-4 shrink-0" aria-hidden />
            {errorMessage}
          </div>
        ) : (
          <>
            {revealed?.token && (
              <div className="space-y-3 rounded-lg border border-primary/40 bg-primary/5 p-4">
                <div className="flex items-start gap-2">
                  <ShieldAlert
                    className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400"
                    aria-hidden
                  />
                  <p className="text-sm">
                    Copy this SCIM token now — you won&apos;t be able to see it
                    again. Paste it as the bearer token in your IdP&apos;s SCIM
                    settings.
                  </p>
                </div>
                <CopyBox value={revealed.token} label="Copy SCIM token" />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setRevealed(null)}
                >
                  Done
                </Button>
              </div>
            )}

            {actionError && (
              <p className="flex items-center gap-2 text-sm text-destructive" role="alert">
                <AlertTriangle className="size-4 shrink-0" aria-hidden />
                {actionError}
              </p>
            )}

            {canManage && (
              <Button type="button" onClick={handleCreate} disabled={minting}>
                {minting ? (
                  <>
                    <Loader2 className="animate-spin" /> Generating…
                  </>
                ) : (
                  <>
                    <KeyRound /> Generate SCIM token
                  </>
                )}
              </Button>
            )}

            {status === "loading" ? (
              <div className="space-y-2">
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
              </div>
            ) : tokens.length === 0 ? (
              <p className="rounded-md border border-dashed border-border p-4 text-center text-sm text-muted-foreground">
                No SCIM tokens yet. Generate one to connect your IdP&apos;s SCIM
                provisioning.
              </p>
            ) : (
              <ul className="divide-y divide-border rounded-lg border border-border">
                {tokens.map((token) => (
                  <li
                    key={token.id}
                    className="flex flex-wrap items-center justify-between gap-3 p-3"
                  >
                    <div className="min-w-0 space-y-0.5">
                      <div className="flex items-center gap-2">
                        <code className="font-mono text-sm">
                          {token.prefix ? `${token.prefix}…` : token.id}
                        </code>
                        {token.revoked ? (
                          <Badge variant="destructive">Revoked</Badge>
                        ) : (
                          <Badge variant="success">Active</Badge>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Created {formatDate(token.created_at)} · Last used{" "}
                        {formatDate(token.last_used_at)}
                      </p>
                    </div>
                    {canManage && !token.revoked && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => handleRevoke(token.id)}
                        disabled={pendingId === token.id}
                        className="text-destructive hover:text-destructive"
                      >
                        {pendingId === token.id ? (
                          <Loader2 className="size-4 animate-spin" aria-hidden />
                        ) : (
                          <Trash2 className="size-4" aria-hidden />
                        )}
                        Revoke
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
