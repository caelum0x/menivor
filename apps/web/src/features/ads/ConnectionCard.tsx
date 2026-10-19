"use client";

import * as React from "react";
import { CheckCircle2, Link2, Unlink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ErrorText, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import { safeServerText } from "@/src/shared/errors";
import { chooseAccount, disconnectAds, getConnection, startConnect, type Connection, type PlatformGate } from "./api";
import { PlatformDisabled } from "./GateNotice";

/** Connect an ad account, then choose the account and the page / identity ads run as. */
export function ConnectionCard({ gate, onChange }: { gate: PlatformGate; onChange?: (c: Connection) => void }) {
  const requestOptions = useRequestOptions();
  const [conn, setConn] = React.useState<Connection | null>(null);
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [accountId, setAccountId] = React.useState("");
  const [identityId, setIdentityId] = React.useState("");
  const [identityName, setIdentityName] = React.useState("");
  const isMeta = gate.platform === "meta";

  const apply = React.useCallback(
    (next: Connection) => {
      setConn(next);
      setAccountId(next.account_id || "");
      setIdentityId(next.identity_id || "");
      onChange?.(next);
    },
    [onChange],
  );

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const next = await getConnection(gate.platform, await requestOptions());
        if (!cancelled) apply(next);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [gate.platform, requestOptions, apply]);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const connect = () =>
    run(async () => {
      const { authorize_url } = await startConnect(gate.platform, await requestOptions());
      window.location.assign(authorize_url);
    });

  const save = () =>
    run(async () => {
      const account = conn?.accounts.find((a) => a.id === accountId);
      apply(
        await chooseAccount(
          gate.platform,
          { account_id: accountId, identity_id: identityId, identity_name: identityId ? "" : identityName, currency: account?.currency },
          await requestOptions(),
        ),
      );
    });

  const disconnect = () =>
    run(async () => {
      await disconnectAds(gate.platform, await requestOptions());
      apply(await getConnection(gate.platform, await requestOptions()));
    });

  const identityLabel = isMeta ? "Facebook Page" : "TikTok ad identity";
  const selectedChanged = accountId !== (conn?.account_id || "") || identityId !== (conn?.identity_id || "");

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
        <CardTitle className="text-base">{gate.label}</CardTitle>
        {conn?.ready ? (
          <Badge variant="success">
            <CheckCircle2 className="h-3 w-3" aria-hidden /> Ready
          </Badge>
        ) : conn?.connected ? (
          <Badge variant="secondary">Choose an account</Badge>
        ) : (
          <Badge variant="outline">Not connected</Badge>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {!gate.enabled ? <PlatformDisabled reason={gate.reason} /> : null}
        {gate.enabled && conn && !conn.connected ? (
          <Button onClick={connect} disabled={busy}>
            <Link2 className="mr-2 h-4 w-4" aria-hidden /> Connect ad account
          </Button>
        ) : null}
        {gate.enabled && conn?.connected ? (
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor={`${gate.platform}-account`}>Ad account</Label>
              <Select id={`${gate.platform}-account`} value={accountId} onChange={(e) => { setAccountId(e.target.value); setIdentityId(""); }}>
                <option value="">Choose an ad account</option>
                {conn.accounts.map((a) => (
                  <option key={a.id} value={a.id} disabled={!a.active}>
                    {a.name} ({a.currency}){a.active ? "" : " — inactive"}
                  </option>
                ))}
              </Select>
            </div>
            {accountId && accountId === conn.account_id ? (
              <div className="space-y-1">
                <Label htmlFor={`${gate.platform}-identity`}>{identityLabel}</Label>
                <Select id={`${gate.platform}-identity`} value={identityId} onChange={(e) => setIdentityId(e.target.value)}>
                  <option value="">{isMeta ? "Choose a Page" : "Create a new identity"}</option>
                  {conn.identities.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name}
                    </option>
                  ))}
                </Select>
                {!isMeta && !identityId ? (
                  <Input
                    aria-label="New identity display name"
                    placeholder="Display name shown on your ads"
                    maxLength={40}
                    value={identityName}
                    onChange={(e) => setIdentityName(e.target.value)}
                  />
                ) : null}
              </div>
            ) : accountId ? (
              <p className="text-xs text-muted-foreground">Save the account first, then pick the {identityLabel.toLowerCase()}.</p>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={save}
                disabled={busy || !accountId || (!selectedChanged && !(!isMeta && !identityId && identityName))}
              >
                Save
              </Button>
              <Button variant="ghost" onClick={disconnect} disabled={busy}>
                <Unlink className="mr-2 h-4 w-4" aria-hidden /> Disconnect
              </Button>
            </div>
            {conn.token_hint ? <p className="text-xs text-muted-foreground">Token {conn.token_hint}, stored encrypted.</p> : null}
          </div>
        ) : null}
        <ErrorText message={error || (conn?.error ? safeServerText(conn.error, "This ad account needs to be reconnected.") : "")} />
      </CardContent>
    </Card>
  );
}
