"use client";

import * as React from "react";
import { AlertTriangle, Building2, Info, Link2Off, Loader2, Plug, RefreshCw } from "lucide-react";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import type { ExtendedPlatform, PlatformRecord, PlatformState } from "../_lib/publishing-api";
import { BlueskyConnectForm } from "./BlueskyConnectForm";
import { PLATFORM_ICONS, STATE_LABELS, TARGET_NOUN } from "./platform-meta";

export interface ExtendedPlatformCardProps {
  record: PlatformRecord;
  busy: boolean;
  error?: string;
  publishingEnabled: boolean;
  onConnect: (platform: ExtendedPlatform, organization: boolean) => void;
  onConnectBluesky: (handle: string, appPassword: string, pds: string) => void;
  onChooseTarget: (platform: ExtendedPlatform, targetId: string) => void;
  onRefreshTargets: (platform: ExtendedPlatform) => void;
  onDisconnect: (platform: ExtendedPlatform) => void;
}

const STATE_VARIANT: Record<PlatformState, BadgeVariant> = {
  not_configured: "secondary",
  plan_required: "secondary",
  not_connected: "outline",
  needs_target: "default",
  needs_reauth: "destructive",
  connected: "success",
};

/** One extended platform: honest availability, connect flow, target choice, disconnect. */
export function ExtendedPlatformCard({
  record,
  busy,
  error,
  publishingEnabled,
  onConnect,
  onConnectBluesky,
  onChooseTarget,
  onRefreshTargets,
  onDisconnect,
}: Readonly<ExtendedPlatformCardProps>) {
  const Icon = PLATFORM_ICONS[record.platform];
  const connection = record.connection;
  const [targetId, setTargetId] = React.useState(connection?.target_id ?? "");
  const targetSelectId = React.useId();

  React.useEffect(() => {
    setTargetId(connection?.target_id || connection?.targets[0]?.id || "");
  }, [connection?.target_id, connection?.targets]);

  const unavailable = record.state === "not_configured" || record.state === "plan_required";
  const noun = TARGET_NOUN[record.target_kind] ?? "destination";
  const targets = connection?.targets ?? [];
  const chooseable = connection && record.target_kind !== "self" ? targets : [];
  const linkedinTargets = record.platform === "linkedin" ? targets : [];

  return (
    <Card className={unavailable ? "opacity-80" : undefined}>
      <CardContent className="flex h-full flex-col gap-4 p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-secondary">
              <Icon className="size-5 text-foreground" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="font-medium leading-tight">{record.label}</p>
              <p className="truncate text-xs text-muted-foreground">
                {connection?.account_name || (connection ? "Connected account" : "Not connected")}
              </p>
            </div>
          </div>
          <Badge variant={STATE_VARIANT[record.state]} className="shrink-0">
            {STATE_LABELS[record.state]}
          </Badge>
        </div>

        {unavailable && (
          <p className="flex items-start gap-2 rounded-md bg-secondary/50 p-3 text-xs text-muted-foreground">
            <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            {record.server_note}
          </p>
        )}

        {connection && record.state === "connected" && connection.target_name && record.target_kind !== "self" && (
          <p className="text-sm">
            Posting to {noun}: <span className="font-medium">{connection.target_name}</span>
          </p>
        )}
        {connection && record.platform === "linkedin" && connection.target_name && (
          <p className="text-sm">
            Posting as: <span className="font-medium">{connection.target_name}</span>
          </p>
        )}

        {connection && (record.state === "needs_target" || chooseable.length > 1 || linkedinTargets.length > 1) && (
          <div className="space-y-2">
            {connection.status_note && (
              <p className="text-xs text-muted-foreground">{connection.status_note}</p>
            )}
            {targets.length > 0 ? (
              <div className="flex gap-2">
                <div className="min-w-0 flex-1">
                  <label htmlFor={targetSelectId} className="sr-only">
                    Where to post
                  </label>
                  <Select
                    id={targetSelectId}
                    value={targetId}
                    disabled={busy}
                    onChange={(e) => setTargetId(e.target.value)}
                  >
                    {targets.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                        {t.kind === "organization" ? " (company page)" : ""}
                      </option>
                    ))}
                  </Select>
                </div>
                <Button
                  size="sm"
                  className="h-10"
                  disabled={busy || !targetId || targetId === connection.target_id}
                  onClick={() => onChooseTarget(record.platform, targetId)}
                >
                  Use
                </Button>
              </div>
            ) : null}
            {record.target_kind !== "self" || record.platform === "linkedin" ? (
              <button
                type="button"
                className="inline-flex items-center gap-1 text-xs text-muted-foreground underline-offset-4 hover:underline"
                disabled={busy}
                onClick={() => onRefreshTargets(record.platform)}
              >
                <RefreshCw className="size-3" aria-hidden /> Refresh list
              </button>
            ) : null}
          </div>
        )}

        {record.state === "needs_reauth" && (
          <p className="flex items-start gap-1.5 text-xs text-destructive">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            {connection?.status_note || `Reconnect ${record.label} to keep posting.`}
          </p>
        )}

        {(record.review_note || record.cost_note) && !unavailable && (
          <p className="text-xs text-muted-foreground">{record.review_note || record.cost_note}</p>
        )}

        <div className="mt-auto space-y-2">
          {!unavailable && !connection && record.auth === "app_password" && publishingEnabled && (
            <BlueskyConnectForm busy={busy} onSubmit={onConnectBluesky} />
          )}

          {!unavailable && record.auth === "oauth2" && (!connection || record.state === "needs_reauth") && (
            <div className="space-y-2">
              <Button
                size="sm"
                className="w-full"
                disabled={busy || !publishingEnabled}
                onClick={() => onConnect(record.platform, false)}
              >
                {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Plug className="size-4" aria-hidden />}
                {connection ? `Reconnect ${record.label}` : `Connect ${record.label}`}
              </Button>
              {record.supports_organization && (
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full"
                  disabled={busy || !publishingEnabled}
                  onClick={() => onConnect(record.platform, true)}
                >
                  <Building2 className="size-4" aria-hidden />
                  Connect with company pages
                </Button>
              )}
            </div>
          )}

          {connection && (
            <div className="flex flex-wrap gap-2">
              {record.auth === "oauth2" && record.state !== "needs_reauth" && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy || !publishingEnabled}
                  onClick={() => onConnect(record.platform, false)}
                >
                  <RefreshCw className="size-4" aria-hidden />
                  Reconnect
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:bg-destructive/10"
                disabled={busy}
                onClick={() => onDisconnect(record.platform)}
              >
                <Link2Off className="size-4" aria-hidden />
                Disconnect
              </Button>
            </div>
          )}

          {!publishingEnabled && !unavailable && !connection && (
            <p className="text-xs text-muted-foreground">
              Connecting accounts opens when direct publishing is enabled for your account.
            </p>
          )}
          {error && (
            <p className="text-xs text-destructive" role="alert">
              {error}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
