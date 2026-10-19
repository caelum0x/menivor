"use client";

import * as React from "react";
import { ExternalLink, Loader2, Plug } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { useApiToken } from "@/lib/use-api-token";
import {
  connectChannel,
  errorMessage,
  type Channel,
  type ChannelKind,
  type ChannelKindInfo,
  type ConnectInput,
} from "@/components/calendar/board-api";

const ORDER: readonly ChannelKind[] = ["telegram", "discord", "mastodon"];

interface Fields {
  bot_token: string;
  chat_id: string;
  webhook_url: string;
  channel_id: string;
  instance: string;
  access_token: string;
  visibility: string;
  label: string;
}

const BLANK: Fields = {
  bot_token: "",
  chat_id: "",
  webhook_url: "",
  channel_id: "",
  instance: "",
  access_token: "",
  visibility: "public",
  label: "",
};

const EMPTY: Record<ChannelKind, Fields> = { telegram: BLANK, discord: BLANK, mastodon: BLANK };

function toInput(kind: ChannelKind, f: Fields): ConnectInput {
  if (kind === "telegram") {
    return { kind, bot_token: f.bot_token.trim(), chat_id: f.chat_id.trim(), label: f.label.trim() };
  }
  if (kind === "discord") {
    return {
      kind,
      webhook_url: f.webhook_url.trim(),
      bot_token: f.bot_token.trim(),
      channel_id: f.channel_id.trim(),
      label: f.label.trim(),
    };
  }
  return {
    kind,
    instance: f.instance.trim(),
    access_token: f.access_token.trim(),
    visibility: (f.visibility as "public" | "unlisted" | "private") || "public",
    label: f.label.trim(),
  };
}

function ready(kind: ChannelKind, f: Fields): boolean {
  if (kind === "telegram") return f.bot_token.trim().length >= 20 && f.chat_id.trim().length >= 2;
  if (kind === "discord") return f.webhook_url.trim().startsWith("https://");
  return f.instance.trim().length >= 3 && f.access_token.trim().length >= 20;
}

function Field({
  id, label, value, onChange, placeholder, secret, hint,
}: Readonly<{
  id: string; label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; secret?: boolean; hint?: string;
}>) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} value={value} placeholder={placeholder} autoComplete="off" spellCheck={false}
        type={secret ? "password" : "text"} onChange={(e) => onChange(e.target.value)} />
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

/** Tabbed connect form; the credential is verified by the API before it is stored. */
export function ConnectChannelForm({
  kinds,
  onConnected,
}: Readonly<{ kinds: ChannelKindInfo[]; onConnected: (channel: Channel) => void }>) {
  const getApiToken = useApiToken();
  const [kind, setKind] = React.useState<ChannelKind>("telegram");
  const [fields, setFields] = React.useState<Record<ChannelKind, Fields>>(EMPTY);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState("");
  const [done, setDone] = React.useState("");
  const info = kinds.find((k) => k.kind === kind);
  const f = fields[kind];
  const set = (key: keyof Fields) => (value: string) =>
    setFields((prev) => ({ ...prev, [kind]: { ...prev[kind], [key]: value } }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    setDone("");
    try {
      const token = await getApiToken();
      const channel = await connectChannel(toInput(kind, f), { token });
      onConnected(channel);
      setFields((prev) => ({ ...prev, [kind]: EMPTY[kind] }));
      setDone(`${channel.label} is connected. Send a test post to check it end to end.`);
    } catch (err) {
      setError(errorMessage(err, "Couldn't connect this channel."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div role="tablist" aria-label="Platform" className="inline-flex rounded-md border border-border p-0.5">
          {ORDER.map((k) => (
            <button key={k} type="button" role="tab" aria-selected={kind === k}
              onClick={() => { setKind(k); setError(""); setDone(""); }}
              className={cn("rounded px-3 py-1.5 text-sm font-medium",
                kind === k ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>
              {kinds.find((x) => x.kind === k)?.label ?? k}
            </button>
          ))}
        </div>

        {info && (
          <div className="space-y-1 text-sm text-muted-foreground">
            <p>{info.help}</p>
            <p>
              {info.cost_note}{" "}
              {info.docs_url && (
                <a href={info.docs_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline">
                  API docs <ExternalLink className="size-3" aria-hidden />
                </a>
              )}
            </p>
          </div>
        )}

        <form onSubmit={(e) => void submit(e)} className="grid gap-4 sm:grid-cols-2">
          {kind === "telegram" && (
            <>
              <Field id="tg-token" label="Bot token" value={f.bot_token} onChange={set("bot_token")} secret
                placeholder="123456789:AA..." hint="From @BotFather. Stored encrypted." />
              <Field id="tg-chat" label="Channel or group" value={f.chat_id} onChange={set("chat_id")}
                placeholder="@yourchannel or -1001234567890" />
            </>
          )}
          {kind === "discord" && (
            <>
              <div className="sm:col-span-2">
                <Field id="dc-hook" label="Webhook URL" value={f.webhook_url} onChange={set("webhook_url")} secret
                  placeholder="https://discord.com/api/webhooks/..." hint="Stored encrypted. Enough for posting." />
              </div>
              <Field id="dc-bot" label="Bot token (optional)" value={f.bot_token} onChange={set("bot_token")} secret
                hint="Only needed to read replies in the inbox." />
              <Field id="dc-channel" label="Channel id (optional)" value={f.channel_id} onChange={set("channel_id")}
                placeholder="Defaults to the webhook's channel" />
            </>
          )}
          {kind === "mastodon" && (
            <>
              <Field id="md-instance" label="Instance" value={f.instance} onChange={set("instance")}
                placeholder="mastodon.social" />
              <Field id="md-token" label="Access token" value={f.access_token} onChange={set("access_token")} secret
                hint="Scopes: read and write. Stored encrypted." />
              <div className="space-y-1.5">
                <Label htmlFor="md-vis">Post visibility</Label>
                <Select id="md-vis" value={f.visibility} onChange={(e) => set("visibility")(e.target.value)}>
                  <option value="public">Public</option>
                  <option value="unlisted">Unlisted</option>
                  <option value="private">Followers only</option>
                </Select>
              </div>
            </>
          )}
          <Field id={`${kind}-label`} label="Name in Menivor (optional)" value={f.label} onChange={set("label")}
            placeholder="For example: Puzzle game updates" />

          <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
            <Button type="submit" disabled={submitting || !ready(kind, f)}>
              {submitting ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Plug className="size-4" aria-hidden />}
              {submitting ? "Checking" : "Connect"}
            </Button>
            {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
            {done && <p className="text-sm text-success" role="status">{done}</p>}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
