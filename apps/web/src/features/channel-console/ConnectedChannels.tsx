"use client";

import * as React from "react";
import { Loader2, Radio } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatWhen, type Channel } from "./api";

interface ConnectedChannelsProps {
  channels: Channel[];
  loading: boolean;
  error: string;
}

/** Read model of the workspace's connected publishing accounts. */
export function ConnectedChannels({ channels, loading, error }: ConnectedChannelsProps) {
  return (
    <section>
      <div className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
        <Radio className="h-4 w-4" aria-hidden /> Connected channels
      </div>

      {loading ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading channels…
        </p>
      ) : error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : channels.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No channels connected yet. Connect an account to schedule and publish.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {channels.map((c) => (
            <Card key={c.provider}>
              <CardContent className="space-y-1 py-4">
                <div className="flex items-center justify-between">
                  <p className="font-medium capitalize">{c.provider}</p>
                  <Badge variant={c.status === "connected" ? "success" : "secondary"}>
                    {c.status}
                  </Badge>
                </div>
                {c.external_account_id && (
                  <p className="text-sm text-muted-foreground">@{c.external_account_id}</p>
                )}
                {c.connected_at && (
                  <p className="text-xs text-muted-foreground">
                    since {formatWhen(c.connected_at)}
                  </p>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}
