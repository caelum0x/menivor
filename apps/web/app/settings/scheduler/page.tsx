"use client";

import * as React from "react";
import { KeyRound, Loader2 } from "lucide-react";

import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import {
  disconnectScheduler,
  listSchedulerConnections,
  listSchedulerTargets,
  providerLabel,
  saveSchedulerKey,
  validateSchedulerKey,
  type SchedulerConnection,
  type SchedulerProvider,
  type SchedulerTarget,
} from "@/src/features/x-scheduler/api";

const KEY_URL: Record<SchedulerProvider, string> = {
  buffer: "https://publish.buffer.com/settings/api",
  typefully: "https://typefully.com/?settings=api",
};

/**
 * Settings → Buffer / Typefully. Keys are write-only: after save, only a
 * masked hint is shown, and disconnect deletes the stored ciphertext.
 */
export default function SchedulerSettingsPage() {
  const getApiToken = useApiToken();
  const [connections, setConnections] = React.useState<SchedulerConnection[]>([]);
  const [targets, setTargets] = React.useState<Partial<Record<SchedulerProvider, SchedulerTarget[]>>>({});
  const [drafts, setDrafts] = React.useState<Record<string, string>>({});
  const [status, setStatus] = React.useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState("");

  const load = React.useCallback(async () => {
    setStatus("loading");
    setError("");
    try {
      const token = await getApiToken();
      const rows = await listSchedulerConnections({ token });
      setConnections(rows);
      const next: Partial<Record<SchedulerProvider, SchedulerTarget[]>> = {};
      for (const row of rows) {
        if (!row.connected) continue;
        next[row.provider] = await listSchedulerTargets(row.provider, { token });
      }
      setTargets(next);
      setStatus("ready");
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not load Buffer and Typefully."));
      setStatus("error");
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const save = async (provider: SchedulerProvider) => {
    const invalid = validateSchedulerKey(drafts[provider] ?? "");
    if (invalid) {
      setError(invalid);
      return;
    }
    setBusy(provider);
    setError("");
    try {
      const token = await getApiToken();
      await saveSchedulerKey(provider, drafts[provider] ?? "", { token });
      setDrafts((current) => ({ ...current, [provider]: "" }));
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not save that key."));
    } finally {
      setBusy("");
    }
  };

  const disconnect = async (provider: SchedulerProvider) => {
    setBusy(provider);
    setError("");
    try {
      const token = await getApiToken();
      await disconnectScheduler(provider, { token });
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not disconnect."));
    } finally {
      setBusy("");
    }
  };

  return (
    <>
      <SettingsHeader active="/settings/scheduler" />
      <main className="container max-w-3xl space-y-6 py-8">
        <div>
          <h1 className="text-2xl font-semibold">Buffer and Typefully</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Paste your own API key to send a finished image or video to X through Buffer or Typefully.
            Menivor stores the key encrypted and never calls the X API. The key is not shown again after you save it.
          </p>
        </div>
        {status === "loading" ? <p className="text-sm text-muted-foreground">Loading…</p> : null}
        {status === "error" ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <div className="grid gap-4">
          {connections.map((row) => (
            <Card key={row.provider}>
              <CardContent className="space-y-3 p-5">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="font-semibold">{providerLabel(row.provider)}</h2>
                  <span className="text-xs text-muted-foreground">{row.connected ? `Saved ${row.key_hint}` : "Not connected"}</span>
                </div>
                <p className="text-sm text-muted-foreground">
                  Create a key in your{" "}
                  <a href={KEY_URL[row.provider]} className="underline underline-offset-2" target="_blank" rel="noreferrer">
                    {providerLabel(row.provider)} settings
                  </a>
                  . Free plans can publish to X until their own limit (Buffer: 10 scheduled posts per channel.
                  Typefully: a monthly publishing quota).
                </p>
                <form
                  className="flex flex-wrap items-end gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void save(row.provider);
                  }}
                >
                  <div className="min-w-[16rem] flex-1 space-y-1">
                    <Label htmlFor={`key-${row.provider}`}>API key</Label>
                    <Input
                      id={`key-${row.provider}`}
                      type="password"
                      autoComplete="off"
                      value={drafts[row.provider] ?? ""}
                      onChange={(event) => setDrafts((current) => ({ ...current, [row.provider]: event.target.value }))}
                      placeholder={row.connected ? "Paste a new key to replace it" : "Paste your API key"}
                    />
                  </div>
                  <Button type="submit" size="sm" disabled={busy !== ""}>
                    {busy === row.provider ? <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden /> : <KeyRound className="mr-1 h-4 w-4" aria-hidden />}
                    Save
                  </Button>
                  {row.connected ? (
                    <Button type="button" size="sm" variant="ghost" disabled={busy !== ""} onClick={() => void disconnect(row.provider)}>
                      Disconnect
                    </Button>
                  ) : null}
                </form>
                {row.connected ? (
                  <ul className="text-sm text-muted-foreground" aria-label={`${providerLabel(row.provider)} X accounts`}>
                    {(targets[row.provider] ?? []).length === 0 ? <li>No X account found on this connection.</li> : null}
                    {(targets[row.provider] ?? []).map((target) => (
                      <li key={target.id}>
                        {target.handle || target.name}
                        {target.organization ? ` · ${target.organization}` : ""}
                        {target.publishing_quota?.remaining != null
                          ? ` · ${target.publishing_quota.remaining} publishes left this period`
                          : ""}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </CardContent>
            </Card>
          ))}
        </div>
        {status === "ready" && error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </main>
    </>
  );
}
