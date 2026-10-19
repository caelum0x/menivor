"use client";

import * as React from "react";
import { Megaphone, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import {
  cardStatus,
  connectAdKey,
  disconnectAd,
  refreshReports,
  setBrandSpaces,
  startAdConnect,
  validateSecret,
  type IntegrationsOverview,
  type ProviderCard,
  type Scope,
} from "../_lib/api";

export interface SectionProps {
  readonly data: IntegrationsOverview;
  readonly scope: Scope;
  readonly getToken: () => Promise<string | null | undefined>;
  readonly onChanged: () => void;
}

function ProviderTile({ card, data, scope, getToken, onChanged }: SectionProps & { card: ProviderCard }) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [keyOpen, setKeyOpen] = React.useState(false);
  const [secret, setSecret] = React.useState("");
  const canManage = data.ads.can_manage;

  const run = async (work: (token: string) => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await work((await getToken()) ?? "");
    } catch (err) {
      setError(friendlyErrorMessage(err, "That did not work. Try again."));
    } finally {
      setBusy(false);
    }
  };

  const connect = () =>
    run(async (token) => {
      if (card.auth === "api_key") {
        setKeyOpen(true);
        return;
      }
      const { authorize_url } = await startAdConnect(card.provider, scope, { token });
      window.location.assign(authorize_url);
    });

  const saveKey = (event: React.FormEvent) => {
    event.preventDefault();
    const invalid = validateSecret(secret, `${card.label} key`);
    if (invalid) {
      setError(invalid);
      return;
    }
    void run(async (token) => {
      await connectAdKey(card.provider, secret, scope, { token });
      setSecret("");
      setKeyOpen(false);
      onChanged();
    });
  };

  const toggleBrand = (accountId: string, current: readonly string[], brandId: string) =>
    run(async (token) => {
      const next = current.includes(brandId) ? current.filter((id) => id !== brandId) : [...current, brandId];
      await setBrandSpaces(accountId, next, scope, { token });
      onChanged();
    });

  const unavailable = !card.configured && card.auth === "oauth";
  const disabled = busy || !canManage || unavailable;
  const needsReauth = card.connected && card.status === "needs_reauth";

  return (
    <Card className="flex flex-col">
      <CardContent className="flex flex-1 flex-col gap-3 p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold">{card.label}</h3>
            <p className="text-xs text-muted-foreground">{card.capabilities}</p>
          </div>
          <Badge
            className="shrink-0 whitespace-nowrap"
            variant={needsReauth ? "destructive" : card.connected && card.account_count > 0 ? "success" : "secondary"}
          >
            {cardStatus(card)}
          </Badge>
        </div>

        {card.accounts.length > 0 ? (
          <ul className="space-y-2 text-sm">
            {card.accounts.map((account) => (
              <li key={account.id} className="rounded-lg border border-white/[0.08] p-2">
                <div className="flex justify-between gap-2">
                  <span className="truncate">{account.name}</span>
                  <span className="text-xs text-muted-foreground">{account.currency}</span>
                </div>
                {data.brand_spaces.length > 0 && canManage ? (
                  <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Brand spaces that see this account">
                    {data.brand_spaces.map((brand) => {
                      const on = account.brand_space_ids.includes(brand.id);
                      return (
                        <button
                          key={brand.id}
                          type="button"
                          aria-pressed={on}
                          disabled={busy}
                          onClick={() => void toggleBrand(account.id, account.brand_space_ids, brand.id)}
                          className={`rounded-full border px-2 py-0.5 text-xs transition-colors ${
                            on ? "border-primary/40 bg-primary/15 text-primary" : "border-white/10 text-muted-foreground"
                          }`}
                        >
                          {brand.name}
                        </button>
                      );
                    })}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}

        {keyOpen ? (
          <form onSubmit={saveKey} className="space-y-2">
            <Input
              type="password"
              autoComplete="off"
              spellCheck={false}
              aria-label={`${card.label} API key`}
              placeholder={`Paste your ${card.label} key`}
              value={secret}
              onChange={(event) => setSecret(event.target.value)}
            />
            <Button type="submit" size="sm" disabled={busy}>Save key</Button>
          </form>
        ) : null}

        {card.last_error ? <p className="text-xs text-destructive">{card.last_error}</p> : null}
        {error ? <p role="alert" className="text-xs text-destructive">{error}</p> : null}

        <div className="mt-auto pt-1">
          {keyOpen ? null : needsReauth ? (
            <Button size="sm" disabled={disabled} onClick={() => void connect()}>
              Reconnect
            </Button>
          ) : card.connected ? (
            <Button variant="outline" size="sm" disabled={busy || !canManage}
              onClick={() => void run(async (token) => { await disconnectAd(card.provider, scope, { token }); onChanged(); })}>
              Disconnect
            </Button>
          ) : unavailable ? (
            <p className="text-xs text-muted-foreground">Menivor is waiting for {card.label} to approve its app.</p>
          ) : (
            <Button size="sm" disabled={disabled} onClick={() => void connect()}>
              Connect
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

/** Ad Accounts: one card per platform; connected accounts feed insights, reporting and ad delivery. */
export function AdAccountsSection(props: SectionProps) {
  const { data, scope, getToken, onChanged } = props;
  const [refreshing, setRefreshing] = React.useState(false);
  const [note, setNote] = React.useState("");
  const anyConnected = data.ads.providers.some((card) => card.connected);

  const refresh = async () => {
    setRefreshing(true);
    setNote("");
    try {
      const out = await refreshReports(scope, { token: (await getToken()) ?? "" });
      setNote(out.errors[0]?.message ?? `Updated ${out.accounts} account(s).`);
      onChanged();
    } catch (err) {
      setNote(friendlyErrorMessage(err, "Could not refresh reports."));
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <section aria-labelledby="ad-accounts" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="ad-accounts" className="flex items-center gap-2 text-xl font-semibold">
            <Megaphone className="size-5 text-primary" aria-hidden />
            Ad Accounts
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Connected accounts feed creative insights, reporting and ad delivery. Choose which accounts each Brand
            space can see. Changes to live ads always wait for your approval.
          </p>
        </div>
        {anyConnected ? (
          <Button variant="outline" size="sm" disabled={refreshing} onClick={() => void refresh()}>
            <RefreshCw className="mr-2 size-4" aria-hidden />
            Refresh reports
          </Button>
        ) : null}
      </div>
      {note ? <p className="text-sm text-muted-foreground">{note}</p> : null}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.ads.providers.map((card) => (
          <ProviderTile key={card.provider} card={card} {...props} />
        ))}
      </div>
    </section>
  );
}
