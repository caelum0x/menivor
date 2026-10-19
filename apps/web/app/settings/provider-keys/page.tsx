"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, KeyRound, RefreshCw, Trash2 } from "lucide-react";
import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import {
  BYOK_DEFAULT_FEE_BPS,
  BYOK_DEFAULT_MIN_FEE_MICROS,
  BYOK_PROVIDERS,
  addProviderKey,
  listProviderKeys,
  providerName,
  revokeProviderKey,
  validateProviderKeyInput,
  type ProviderKey,
} from "@/lib/byok";
import { formatUsdMicros } from "@/lib/marketplace";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

function messageFor(error: unknown, fallback: string): string {
  return friendlyErrorMessage(error, fallback);
}

function formatDate(value: string | null): string {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleDateString();
}

/**
 * Settings -> Provider keys (BYOK). Store your own fal.ai, Kling, ElevenLabs
 * and other provider keys; generation stages that use those providers then
 * route through your account. Keys are write-only: after saving, only a masked
 * hint is ever shown, and revoking takes effect immediately.
 */
export default function ProviderKeysPage() {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [keys, setKeys] = React.useState<readonly ProviderKey[]>([]);
  const [loadError, setLoadError] = React.useState("");

  const [provider, setProvider] = React.useState(BYOK_PROVIDERS[0]?.key ?? "elevenlabs");
  const [secret, setSecret] = React.useState("");
  const [label, setLabel] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [formError, setFormError] = React.useState("");
  const [revoking, setRevoking] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setStatus("loading");
    setLoadError("");
    try {
      const token = await getApiToken();
      setKeys(await listProviderKeys({ token }));
      setStatus("ready");
    } catch (error) {
      setLoadError(messageFor(error, "Could not load your provider keys."));
      setStatus("error");
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const input = { provider_key: provider, secret, label };
    const invalid = validateProviderKeyInput(input);
    if (invalid) {
      setFormError(invalid);
      return;
    }
    setSaving(true);
    setFormError("");
    try {
      const token = await getApiToken();
      const created = await addProviderKey(input, { token });
      setKeys((current) => [created, ...current.filter((key) => key.id !== created.id)]);
      setSecret("");
      setLabel("");
      setStatus("ready");
    } catch (error) {
      setFormError(messageFor(error, "Could not save the key."));
    } finally {
      setSaving(false);
    }
  };

  const revoke = async (id: string) => {
    setRevoking(id);
    setLoadError("");
    try {
      const token = await getApiToken();
      const revoked = await revokeProviderKey(id, { token });
      setKeys((current) =>
        current.map((key) => (key.id === id ? { ...key, ...revoked, status: revoked.status || "revoked" } : key)),
      );
    } catch (error) {
      setLoadError(messageFor(error, "Could not revoke the key."));
    } finally {
      setRevoking(null);
    }
  };

  const selected = BYOK_PROVIDERS.find((entry) => entry.key === provider);

  return (
    <main className="min-h-dvh">
      <SettingsHeader active="/settings/provider-keys" />

      <section className="container py-10">
        <div className="mx-auto max-w-4xl space-y-6">
          <div>
            <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
              <KeyRound className="size-7 text-primary" aria-hidden />
              Provider keys
            </h1>
            <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
              Bring your own keys for video, voice and script providers. When a
              generation stage uses a provider you have a key for, it runs on
              your provider account and the provider bills you directly. Menivor
              then charges a routing fee instead of the provider price:{" "}
              {BYOK_DEFAULT_FEE_BPS / 100}% of the equivalent provider price, with
              a {formatUsdMicros(BYOK_DEFAULT_MIN_FEE_MICROS)} minimum per stage.
              Each stage&apos;s fee is listed on{" "}
              <Link href="/spend" className="text-primary underline underline-offset-4">
                Spend &amp; usage
              </Link>
              , where routing through your keys must also be switched on.
            </p>
          </div>

          <div className="grid gap-6 lg:grid-cols-[minmax(0,360px)_1fr]">
            <Card className="lg:self-start">
              <CardContent className="p-5">
                <form onSubmit={(event) => void submit(event)} className="space-y-4">
                  <h2 className="text-lg font-semibold">Add a key</h2>
                  <div className="space-y-1.5">
                    <Label htmlFor="byok-provider">Provider</Label>
                    <Select
                      id="byok-provider"
                      value={provider}
                      onChange={(event) => setProvider(event.target.value)}
                    >
                      {BYOK_PROVIDERS.map((entry) => (
                        <option key={entry.key} value={entry.key}>
                          {entry.name} ({entry.kind})
                        </option>
                      ))}
                    </Select>
                    {selected ? (
                      <a
                        href={selected.keyUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-primary underline underline-offset-4"
                      >
                        Get a {selected.name} API key
                      </a>
                    ) : null}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="byok-secret">API key</Label>
                    <Input
                      id="byok-secret"
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      value={secret}
                      onChange={(event) => setSecret(event.target.value)}
                      placeholder="Paste the provider key"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="byok-label">Label (optional)</Label>
                    <Input
                      id="byok-label"
                      maxLength={80}
                      value={label}
                      onChange={(event) => setLabel(event.target.value)}
                      placeholder="e.g. Agency account"
                    />
                  </div>
                  {formError ? (
                    <p role="alert" className="text-sm text-destructive">
                      {formError}
                    </p>
                  ) : null}
                  <Button type="submit" className="w-full" disabled={saving || !secret.trim()}>
                    {saving ? "Saving..." : "Save key"}
                  </Button>
                  <p className="text-xs text-muted-foreground">
                    The key is encrypted before it is stored and is never shown
                    again. Only a masked hint appears in the list.
                  </p>
                </form>
              </CardContent>
            </Card>

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">Your keys</h2>
                <Button variant="outline" size="sm" onClick={() => void load()} disabled={status === "loading"}>
                  <RefreshCw className={status === "loading" ? "size-4 animate-spin" : "size-4"} aria-hidden />
                  Refresh
                </Button>
              </div>

              {loadError ? (
                <Card>
                  <CardContent className="flex items-center gap-2 py-4 text-sm text-destructive" role="alert">
                    <AlertTriangle className="size-4" aria-hidden />
                    {loadError}
                  </CardContent>
                </Card>
              ) : null}

              {status === "loading" ? (
                <div className="space-y-2">
                  <Skeleton className="h-16 w-full" />
                  <Skeleton className="h-16 w-full" />
                </div>
              ) : status === "ready" && keys.length === 0 ? (
                <Card>
                  <CardContent className="py-8 text-center text-sm text-muted-foreground">
                    No provider keys yet. Generations use Menivor&apos;s provider
                    accounts and are billed at the listed price.
                  </CardContent>
                </Card>
              ) : (
                <ul className="space-y-2">
                  {keys.map((key) => {
                    const active = key.status === "active";
                    return (
                      <li key={key.id}>
                        <Card>
                          <CardContent className="flex items-center justify-between gap-4 py-4">
                            <div className="min-w-0">
                              <p className="font-medium">
                                {providerName(key.provider_key)}
                                {key.label ? (
                                  <span className="ml-2 text-sm font-normal text-muted-foreground">{key.label}</span>
                                ) : null}
                              </p>
                              <p className="mt-0.5 text-xs text-muted-foreground">
                                <span className="font-mono">{key.key_prefix}</span> · added{" "}
                                {formatDate(key.created_at)} · used {key.use_count} times · last used{" "}
                                {formatDate(key.last_used_at)}
                              </p>
                            </div>
                            {active ? (
                              <Button
                                variant="outline"
                                size="sm"
                                disabled={revoking === key.id}
                                onClick={() => void revoke(key.id)}
                              >
                                <Trash2 className="size-4" aria-hidden />
                                {revoking === key.id ? "Revoking..." : "Revoke"}
                              </Button>
                            ) : (
                              <span className="text-xs uppercase tracking-wide text-muted-foreground">
                                {key.status}
                              </span>
                            )}
                          </CardContent>
                        </Card>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
