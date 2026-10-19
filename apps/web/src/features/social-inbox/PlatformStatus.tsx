"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, CircleSlash, Plug } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { accessLabel } from "./format";
import { CHANNEL_INBOX_PLATFORMS, EXTENDED_INBOX_PLATFORMS, type Access, type InboxPlatform, type PlatformCapability } from "./types";

interface PlatformStatusProps {
  platforms: PlatformCapability[];
  needsReplyByPlatform: Record<string, number>;
  reconnecting: InboxPlatform | null;
  onReconnect: (platform: InboxPlatform, scopes: string) => void;
}

function AccessRow({ label, access }: { label: string; access: Access }) {
  const icon =
    access.read === "yes" ? (
      <CheckCircle2 className="size-4 text-success" aria-hidden />
    ) : access.read === "needs_permission" ? (
      <AlertTriangle className="size-4 text-amber-500" aria-hidden />
    ) : (
      <CircleSlash className="size-4 text-muted-foreground" aria-hidden />
    );
  const replyNote =
    access.read === "yes" && access.reply !== "yes" ? ` (replies: ${accessLabel(access.reply)})` : "";
  return (
    <div className="flex items-start gap-2 text-sm">
      <span className="mt-0.5">{icon}</span>
      <div>
        <p>
          <span className="font-medium">{label}:</span> {accessLabel(access.read)}
          {replyNote}
        </p>
        {access.note && <p className="text-xs text-muted-foreground">{access.note}</p>}
      </div>
    </div>
  );
}

/**
 * Connected platforms get a card each (what the platform lets us do, what is
 * waiting); platforms that are not connected are listed once, compactly.
 */
export function PlatformStatus({
  platforms,
  needsReplyByPlatform,
  reconnecting,
  onReconnect,
}: PlatformStatusProps) {
  const connected = platforms.filter((p) => p.connected);
  const notConnected = platforms.filter((p) => !p.connected);
  return (
    <div className="space-y-3">
      {connected.length > 0 && (
        <div className="grid gap-3 md:grid-cols-3">
          {connected.map((p) => (
            <Card key={p.platform}>
              <CardContent className="space-y-3 p-4">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-semibold">{p.label}</p>
                  <Badge variant="success">Connected</Badge>
                </div>
                <AccessRow label="Comments" access={p.comments} />
                <AccessRow label="Direct messages" access={p.dms} />
                <p className="text-xs text-muted-foreground">
                  {needsReplyByPlatform[p.platform] ?? 0} waiting for a reply
                </p>
                {p.needs_reconnect &&
                  (EXTENDED_INBOX_PLATFORMS.has(p.platform) ? (
                    <Button asChild size="sm" variant="outline">
                      <Link href="/connections">
                        <Plug className="size-4" aria-hidden /> Reconnect on Connections
                      </Link>
                    </Button>
                  ) : (
                    p.reconnect_scopes && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={reconnecting !== null}
                        onClick={() => onReconnect(p.platform, p.reconnect_scopes)}
                      >
                        <Plug className="size-4" aria-hidden />
                        {reconnecting === p.platform ? "Opening..." : "Reconnect with inbox access"}
                      </Button>
                    )
                  ))}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      {notConnected.length > 0 && (
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div className="text-sm">
              <p className="font-medium">Not connected</p>
              <p className="text-muted-foreground">
                {notConnected.map((p) => p.label).join(", ")}. Connect them to see comments on the posts
                Menivor publishes there.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button asChild size="sm" variant="outline">
                <Link href="/connections">
                  <Plug className="size-4" aria-hidden /> Connections
                </Link>
              </Button>
              {notConnected.some((p) => CHANNEL_INBOX_PLATFORMS.has(p.platform)) && (
                <Button asChild size="sm" variant="outline">
                  <Link href="/calendar/channels">
                    <Plug className="size-4" aria-hidden /> Telegram, Discord, Mastodon
                  </Link>
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
