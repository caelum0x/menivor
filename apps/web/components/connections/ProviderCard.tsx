"use client";

import * as React from "react";
import { Link2, Link2Off, Loader2, Plug, RefreshCw } from "lucide-react";
import type { Connection, SocialProvider } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConnectionStatusBadge } from "@/components/connections/ConnectionStatusBadge";
import {
  formatScopes,
  formatTimestamp,
  isConnectionExpired,
} from "@/components/connections/format";
import { providerIcon, providerLabel } from "@/components/connections/providers";

export interface ProviderCardProps {
  provider: SocialProvider;
  /** The caller's connection for this provider, if any (TOKEN-FREE). */
  connection?: Connection;
  connecting: boolean;
  disconnecting: boolean;
  /** Per-card error surfaced under the actions (connect/disconnect failure). */
  error?: string;
  onConnect: (provider: SocialProvider) => void;
  onDisconnect: (provider: SocialProvider) => void;
}

/**
 * One provider row: shows the connected account (provider-side id, status,
 * granted scopes, connected/expiry timestamps) with a Reconnect + Disconnect
 * pair, or a single Connect call-to-action when the provider is not yet linked.
 * SECURITY: only the token-free {@link Connection} fields are ever rendered.
 */
export function ProviderCard({
  provider,
  connection,
  connecting,
  disconnecting,
  error,
  onConnect,
  onDisconnect,
}: Readonly<ProviderCardProps>) {
  const Icon = providerIcon(provider);
  const label = providerLabel(provider);
  const isConnected = Boolean(connection?.connected);
  const scopes = connection ? formatScopes(connection.scopes) : [];
  const expired = connection ? isConnectionExpired(connection) : false;
  const busy = connecting || disconnecting;

  return (
    <Card>
      <CardContent className="flex h-full flex-col gap-4 p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-secondary">
              <Icon className="size-5 text-foreground" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="font-medium leading-tight">{label}</p>
              {isConnected && connection?.external_account_id ? (
                <p className="truncate text-xs text-muted-foreground">
                  {connection.external_account_id}
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">Not connected</p>
              )}
            </div>
          </div>
          {isConnected && connection && (
            <ConnectionStatusBadge connection={connection} />
          )}
        </div>

        {isConnected && connection && (
          <dl className="space-y-2 text-xs text-muted-foreground">
            {scopes.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {scopes.map((scope) => (
                  <Badge key={scope} variant="outline">
                    {scope}
                  </Badge>
                ))}
              </div>
            )}
            <div className="flex justify-between gap-3">
              <dt>Connected</dt>
              <dd className="text-foreground">
                {formatTimestamp(connection.connected_at)}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt>Token expires</dt>
              <dd className={expired ? "text-destructive" : "text-foreground"}>
                {formatTimestamp(connection.token_expires_at)}
              </dd>
            </div>
          </dl>
        )}

        <div className="mt-auto space-y-2">
          {isConnected ? (
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => onConnect(provider)}
              >
                {connecting ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <RefreshCw className="size-4" aria-hidden />
                )}
                Reconnect
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:bg-destructive/10"
                disabled={busy}
                onClick={() => onDisconnect(provider)}
              >
                {disconnecting ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <Link2Off className="size-4" aria-hidden />
                )}
                Disconnect
              </Button>
            </div>
          ) : (
            <Button
              size="sm"
              className="w-full"
              disabled={busy}
              onClick={() => onConnect(provider)}
            >
              {connecting ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Plug className="size-4" aria-hidden />
              )}
              Connect {label}
            </Button>
          )}
          {expired && isConnected && (
            <p className="flex items-center gap-1.5 text-xs text-destructive">
              <Link2 className="size-3.5" aria-hidden />
              Reconnect to keep publishing to {label}.
            </p>
          )}
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
      </CardContent>
    </Card>
  );
}
