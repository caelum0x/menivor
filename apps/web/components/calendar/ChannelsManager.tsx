"use client";

import * as React from "react";
import { CheckCircle2, ExternalLink, Loader2, RefreshCw, Send, Trash2, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useApiToken } from "@/lib/use-api-token";
import { ConnectChannelForm } from "@/components/calendar/ConnectChannelForm";
import {
  disconnectChannel,
  errorMessage,
  getChannels,
  testChannel,
  verifyChannel,
  type Channel,
  type ChannelsOverview,
} from "@/components/calendar/board-api";

type RowNote = { tone: "ok" | "error"; text: string; url?: string };

const STATUS_BADGE: Record<string, { label: string; variant: "success" | "destructive" | "secondary" }> = {
  connected: { label: "Connected", variant: "success" },
  needs_reauth: { label: "Reconnect", variant: "destructive" },
  error: { label: "Check failed", variant: "destructive" },
};

/**
 * Connected Telegram / Discord / Mastodon channels: connect, re-check, send a
 * test post, and disconnect. Tokens never come back from the API; only the
 * channel name, status and what the inbox can read are shown.
 */
export function ChannelsManager() {
  const getApiToken = useApiToken();
  const [data, setData] = React.useState<ChannelsOverview | null>(null);
  const [status, setStatus] = React.useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = React.useState("");
  const [busy, setBusy] = React.useState<string | null>(null);
  const [notes, setNotes] = React.useState<Record<string, RowNote>>({});
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    (async () => {
      try {
        const token = await getApiToken();
        const overview = await getChannels({ token });
        if (cancelled) return;
        setData(overview);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        setLoadError(errorMessage(err, "Couldn't load your channels."));
        setStatus("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getApiToken, nonce]);

  const replace = (next: Channel) =>
    setData((prev) =>
      prev ? { ...prev, channels: prev.channels.map((c) => (c.id === next.id ? next : c)) } : prev,
    );
  const note = (id: string, value: RowNote) => setNotes((prev) => ({ ...prev, [id]: value }));

  const run = async (id: string, action: "verify" | "test" | "remove") => {
    if (action === "remove" && !window.confirm("Disconnect this channel? Posts not yet sent to it are canceled.")) {
      return;
    }
    setBusy(`${action}:${id}`);
    try {
      const token = await getApiToken();
      if (action === "verify") {
        const updated = await verifyChannel(id, { token });
        replace(updated);
        note(id, updated.last_error
          ? { tone: "error", text: updated.last_error }
          : { tone: "ok", text: "The credential still works." });
      } else if (action === "test") {
        const post = await testChannel(id, "", { token });
        note(id, post.status === "published"
          ? { tone: "ok", text: "Test post sent.", url: post.url }
          : { tone: "error", text: post.error || `The test post is ${post.status}.` });
      } else {
        const result = await disconnectChannel(id, { token });
        setData((prev) => (prev ? { ...prev, channels: prev.channels.filter((c) => c.id !== id) } : prev));
        if (result.canceled_posts > 0) {
          window.alert(`${result.canceled_posts} scheduled post(s) to that channel were canceled.`);
        }
      }
    } catch (err) {
      note(id, { tone: "error", text: errorMessage(err, "That did not work. Try again.") });
    } finally {
      setBusy(null);
    }
  };

  if (status === "loading" && !data) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }
  if (status === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="flex items-center justify-between gap-3 p-5 text-sm">
          <span>{loadError}</span>
          <Button size="sm" variant="outline" onClick={() => setNonce((n) => n + 1)}>
            <RefreshCw className="size-4" aria-hidden /> Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  const channels = data?.channels ?? [];
  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Connected channels</h2>
        {channels.length === 0 ? (
          <p className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
            Nothing connected yet. Add a channel below; each one is checked against the platform before it
            is saved.
          </p>
        ) : (
          <ul className="space-y-3">
            {channels.map((c) => {
              const badge = STATUS_BADGE[c.status] ?? { label: c.status, variant: "secondary" as const };
              const rowNote = notes[c.id];
              return (
                <li key={c.id}>
                  <Card>
                    <CardContent className="space-y-3 p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0 space-y-1">
                          <p className="flex flex-wrap items-center gap-2 font-medium">
                            {c.label}
                            <Badge variant="outline">{c.kind_label}</Badge>
                            <Badge variant={badge.variant}>{badge.label}</Badge>
                            {c.shared && (
                              <Badge variant="secondary">
                                <Users className="mr-1 size-3" aria-hidden /> Workspace
                              </Badge>
                            )}
                          </p>
                          <p className="truncate text-xs text-muted-foreground">
                            {c.target_name}
                            {c.public_url && (
                              <>
                                {" - "}
                                <a href={c.public_url} target="_blank" rel="noreferrer" className="underline-offset-4 hover:underline">
                                  open <ExternalLink className="inline size-3" aria-hidden />
                                </a>
                              </>
                            )}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            Inbox: {c.inbox.reads ? "reads replies" : "posting only"}. {c.inbox.note}
                          </p>
                          {c.last_error && <p className="text-xs text-destructive">{c.last_error}</p>}
                        </div>
                        <div className="flex shrink-0 flex-wrap gap-2">
                          <Button size="sm" variant="outline" disabled={!c.can_post || busy !== null}
                            onClick={() => void run(c.id, "test")}>
                            {busy === `test:${c.id}` ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
                            Send test
                          </Button>
                          {c.can_manage && (
                            <>
                              <Button size="sm" variant="outline" disabled={busy !== null}
                                onClick={() => void run(c.id, "verify")}>
                                {busy === `verify:${c.id}` ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <RefreshCw className="size-4" aria-hidden />}
                                Re-check
                              </Button>
                              <Button size="sm" variant="ghost" aria-label={`Disconnect ${c.label}`} disabled={busy !== null}
                                onClick={() => void run(c.id, "remove")}>
                                <Trash2 className="size-4" aria-hidden />
                              </Button>
                            </>
                          )}
                        </div>
                      </div>
                      {rowNote && (
                        <p className={rowNote.tone === "ok" ? "flex items-center gap-1.5 text-xs text-success" : "text-xs text-destructive"}>
                          {rowNote.tone === "ok" && <CheckCircle2 className="size-3.5" aria-hidden />}
                          {rowNote.text}
                          {rowNote.url && (
                            <a href={rowNote.url} target="_blank" rel="noreferrer" className="ml-1 underline">
                              View it
                            </a>
                          )}
                        </p>
                      )}
                    </CardContent>
                  </Card>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Add a channel</h2>
        <ConnectChannelForm
          kinds={data?.kinds ?? []}
          onConnected={(channel) =>
            setData((prev) => {
              if (!prev) return prev;
              const rest = prev.channels.filter((c) => c.id !== channel.id);
              return { ...prev, channels: [...rest, channel] };
            })
          }
        />
      </section>
    </div>
  );
}
