"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { KeyRound, Plus, RefreshCw } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  bpsToPercent,
  createKey,
  formatUsdMicros,
  listKeys,
  type ProvisioningKey,
} from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** Per-client resale keys: mint a key with a daily cap + markup; list them. */
export function AgencyKeys() {
  const { getToken } = useAuth();
  const [keys, setKeys] = React.useState<ProvisioningKey[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [secret, setSecret] = React.useState<{ label: string; secret: string } | null>(null);

  const [label, setLabel] = React.useState("");
  const [dailyCapUsd, setDailyCapUsd] = React.useState(50);
  const [markupBps, setMarkupBps] = React.useState(3000);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      const { keys: rows } = await listKeys({ token });
      setKeys(rows);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed to load keys."));
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const onCreate = React.useCallback(async () => {
    setBusy(true);
    setError("");
    setSecret(null);
    try {
      const token = (await getToken()) ?? undefined;
      const created = await createKey(
        {
          label: label.trim() || "Client key",
          daily_cap_micros: Math.round(dailyCapUsd * 1_000_000),
          markup_bps: markupBps,
        },
        { token },
      );
      if (created.secret) setSecret({ label: created.label, secret: created.secret });
      setLabel("");
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed to create key."));
    } finally {
      setBusy(false);
    }
  }, [label, dailyCapUsd, markupBps, getToken, load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Client keys</h2>
        <Button size="sm" variant="ghost" onClick={() => void load()} aria-label="Refresh">
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      <Card>
        <CardContent className="space-y-3 py-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label className="mb-1 block text-sm font-medium">Client label</label>
              <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Acme Co." />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Daily cap ($)</label>
              <Input type="number" value={dailyCapUsd} min={1} onChange={(e) => setDailyCapUsd(Number(e.target.value) || 0)} />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Markup (bps · {bpsToPercent(markupBps)})</label>
              <Input type="number" value={markupBps} step={50} min={0} onChange={(e) => setMarkupBps(Number(e.target.value) || 0)} />
            </div>
          </div>
          <Button onClick={onCreate} disabled={busy}>
            <Plus className="mr-1 h-4 w-4" /> Mint client key
          </Button>
        </CardContent>
      </Card>

      {secret ? (
        <Card>
          <CardContent className="space-y-1 py-4">
            <Badge variant="secondary">Copy now — shown once</Badge>
            <div className="text-sm text-muted-foreground">{secret.label}</div>
            <code className="block break-all rounded bg-muted px-2 py-1 text-xs">{secret.secret}</code>
          </CardContent>
        </Card>
      ) : null}

      {error ? <Card><CardContent className="py-4 text-sm text-red-600">{error}</CardContent></Card> : null}

      <div className="space-y-2">
        {loading ? (
          <Card><CardContent className="py-6 text-sm text-muted-foreground">Loading…</CardContent></Card>
        ) : keys.length === 0 ? (
          <Card><CardContent className="flex items-center gap-2 py-6 text-sm text-muted-foreground"><KeyRound className="h-4 w-4" /> No client keys yet.</CardContent></Card>
        ) : (
          keys.map((k) => (
            <Card key={k.id}>
              <CardContent className="flex items-center justify-between py-3">
                <div>
                  <div className="font-medium">{k.label}</div>
                  <div className="text-xs text-muted-foreground">
                    cap {formatUsdMicros(k.daily_cap_micros)}/day · markup {bpsToPercent(k.markup_bps)}
                  </div>
                </div>
                <Badge variant={k.disabled ? "outline" : "secondary"}>{k.disabled ? "disabled" : "active"}</Badge>
              </CardContent>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
