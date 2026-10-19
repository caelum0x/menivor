"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, Loader2, Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

import {
  listAccounts,
  listProviders,
  startConnect,
  type Account,
  type Provider,
  type ProviderState,
} from "./api";
import { PROVIDER_LABEL } from "./plan";

type Load = "loading" | "ready" | "error";

/** Connected accounts, grouped by platform. One action: connect another account. */
export function AccountsScreen() {
  const [load, setLoad] = React.useState<Load>("loading");
  const [error, setError] = React.useState("");
  const [providers, setProviders] = React.useState<ProviderState[]>([]);
  const [accounts, setAccounts] = React.useState<Account[]>([]);
  const [connecting, setConnecting] = React.useState<Provider | "">("");

  const reload = React.useCallback(async () => {
    setLoad("loading");
    try {
      const [p, a] = await Promise.all([listProviders(), listAccounts()]);
      setProviders(p.providers);
      setAccounts(a.accounts);
      setLoad("ready");
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not load your accounts."));
      setLoad("error");
    }
  }, []);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const connect = async (provider: Provider) => {
    setConnecting(provider);
    setError("");
    try {
      const { authorize_url } = await startConnect(provider);
      window.location.assign(authorize_url);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not start connecting. Try again."));
      setConnecting("");
    }
  };

  if (load === "loading") {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden /> Loading accounts
      </p>
    );
  }
  if (load === "error") {
    return (
      <div role="alert" className="space-y-3 text-sm">
        <p>{error}</p>
        <Button variant="outline" size="sm" onClick={() => void reload()}>
          Try again
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {providers.map((p) => (
        <ProviderSection
          key={p.provider}
          state={p}
          accounts={accounts.filter((a) => a.provider === p.provider)}
          busy={connecting === p.provider}
          onConnect={() => void connect(p.provider)}
        />
      ))}
    </div>
  );
}

function ProviderSection({
  state,
  accounts,
  busy,
  onConnect,
}: {
  state: ProviderState;
  accounts: Account[];
  busy: boolean;
  onConnect: () => void;
}) {
  return (
    <section aria-labelledby={`provider-${state.provider}`} className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h2 id={`provider-${state.provider}`} className="text-lg font-semibold">
          {state.label}
        </h2>
        {state.ready ? (
          <Button size="sm" variant="secondary" onClick={onConnect} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Plus aria-hidden />}
            Connect {accounts.length > 0 ? "another" : "an"} account
          </Button>
        ) : null}
      </div>
      {!state.ready ? <NotSetUp state={state} /> : null}
      {state.notes.map((note) => (
        <p key={note} className="text-xs text-muted-foreground">
          {note}
        </p>
      ))}
      {accounts.length === 0 && state.ready ? (
        <p className="text-sm text-muted-foreground">No {state.label} accounts yet.</p>
      ) : null}
      <ul className="grid gap-2">
        {accounts.map((a) => (
          <li key={a.id}>
            <AccountRow account={a} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function NotSetUp({ state }: { state: ProviderState }) {
  return (
    <Card>
      <CardContent className="space-y-2 p-4 text-sm">
        <p className="flex items-center gap-2 font-medium">
          <AlertTriangle className="size-4 text-muted-foreground" aria-hidden />
          Connect your developer app first
        </p>
        <p className="text-muted-foreground">
          {state.label} posting needs a {state.label} developer app on this server. An admin adds
          these settings, then accounts can be connected here:
        </p>
        <ul className="list-inside list-disc text-xs text-muted-foreground">
          {state.missing_settings.map((name) => (
            <li key={name}>
              <code>{name}</code>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function AccountRow({ account }: { account: Account }) {
  const name = account.display_name || account.handle || PROVIDER_LABEL[account.provider];
  return (
    <Card>
      <CardContent className="flex items-center justify-between gap-3 p-3">
        <div className="flex min-w-0 items-center gap-3">
          {account.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- platform avatar URL
            <img src={account.avatar_url} alt="" className="size-9 rounded-full object-cover" />
          ) : (
            <span aria-hidden className="size-9 rounded-full bg-white/[0.06]" />
          )}
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{name}</p>
            <p className="text-xs text-muted-foreground">
              {account.posts_last_24h} of {account.daily_cap} posts in the last day
              {account.shared ? " · shared with your team" : ""}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {account.status === "needs_reauth" ? <Badge variant="destructive">Reconnect</Badge> : null}
          {account.status === "paused" ? <Badge variant="secondary">Paused</Badge> : null}
          <Link
            href={`/autopost/accounts/${encodeURIComponent(account.id)}`}
            className="text-sm text-primary underline-offset-4 hover:underline"
          >
            Pace
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
