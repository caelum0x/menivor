"use client";

import * as React from "react";
import Link from "next/link";
import { Store } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import {
  addPlayApp,
  connectAppStore,
  connectPlay,
  disconnectStore,
  listAppStoreApps,
  listPlayApps,
  listStoreConnections,
  type StoreApp,
  type StoreConnection,
} from "../_lib/api";

type Provider = "appstore" | "play";

/** Deep-link a connected app straight into the free App Store Audit tool
 * (`/tools/app-store-audit`), so a creator never has to copy/paste their own
 * listing's URL by hand. */
function auditHref(app: StoreApp): string {
  const storeUrl = app.id
    ? `https://apps.apple.com/app/id${app.id}`
    : `https://play.google.com/store/apps/details?id=${app.package_name}`;
  return `/tools/app-store-audit?url=${encodeURIComponent(storeUrl)}`;
}

interface Props {
  readonly getToken: () => Promise<string | null | undefined>;
}

/**
 * Phase 3 "Connect your store": paste an App Store Connect API key or a Play
 * service-account JSON so Menivor can read a creator's own apps' current
 * version and rating and feed them into the App Store Audit tool. Not
 * workspace-scoped (a developer account belongs to the signed-in user, not a
 * Brand space), so this section loads and manages its own data independently
 * of the rest of the Integrations page.
 */
export function StoreConnectSection({ getToken }: Props) {
  const [connections, setConnections] = React.useState<StoreConnection[] | null>(null);
  const [apps, setApps] = React.useState<Record<Provider, StoreApp[]>>({ appstore: [], play: [] });
  const [open, setOpen] = React.useState<Provider | null>(null);
  const [fields, setFields] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState<string>("");
  const [error, setError] = React.useState("");
  const field = (key: string) => fields[key] ?? "";
  const set = (key: string) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setFields((current) => ({ ...current, [key]: event.target.value }));

  const load = React.useCallback(async () => {
    try {
      const token = (await getToken()) ?? "";
      const { connections: rows } = await listStoreConnections({ token });
      setConnections(rows);
      for (const row of rows) {
        if (row.provider === "appstore") {
          setApps((current) => ({ ...current, appstore: [] }));
          listAppStoreApps({ token }).then(({ apps: a }) => setApps((c) => ({ ...c, appstore: a }))).catch(() => {});
        }
        if (row.provider === "play") {
          listPlayApps({ token }).then(({ apps: a }) => setApps((c) => ({ ...c, play: a }))).catch(() => {});
        }
      }
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not load connected stores."));
    }
  }, [getToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const connectionFor = (provider: Provider) => connections?.find((c) => c.provider === provider) ?? null;

  const submitAppStore = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setBusy("appstore");
    try {
      const token = (await getToken()) ?? "";
      await connectAppStore(field("issuerId"), field("keyId"), field("privateKey"), { token });
      setFields({});
      setOpen(null);
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "That App Store Connect key didn't work."));
    } finally {
      setBusy("");
    }
  };

  const submitPlay = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setBusy("play");
    try {
      const token = (await getToken()) ?? "";
      await connectPlay(field("playJson"), { token });
      setFields({});
      setOpen(null);
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "That Play service-account key didn't work."));
    } finally {
      setBusy("");
    }
  };

  const addPackage = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setBusy("play-app");
    try {
      const token = (await getToken()) ?? "";
      await addPlayApp(field("packageName"), { token });
      setFields((current) => ({ ...current, packageName: "" }));
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not read that Play package."));
    } finally {
      setBusy("");
    }
  };

  const disconnect = async (provider: Provider) => {
    setBusy(provider);
    setError("");
    try {
      await disconnectStore(provider, { token: (await getToken()) ?? "" });
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not disconnect."));
    } finally {
      setBusy("");
    }
  };

  const onFilePasted = (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setFields((current) => ({ ...current, [key]: String(reader.result || "") }));
    reader.readAsText(file);
  };

  if (connections === null) return null;

  const appstore = connectionFor("appstore");
  const play = connectionFor("play");

  return (
    <section aria-labelledby="store-connect" className="space-y-4">
      <div>
        <h2 id="store-connect" className="flex items-center gap-2 text-xl font-semibold">
          <Store className="size-5 text-primary" aria-hidden />
          Connect your store
        </h2>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Connect App Store Connect or Google Play so the App Store Audit tool reads your own apps&apos; current
          version and rating automatically.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardContent className="flex h-full flex-col gap-3 p-5">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-semibold">App Store Connect</h3>
              <Badge variant={appstore ? "success" : "secondary"}>
                {appstore ? "Connected" : "Not connected"}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              {appstore ? `Issuer ${appstore.account_name}` : "Users and Access -> Integrations -> App Store Connect API."}
            </p>
            {open === "appstore" ? (
              <form onSubmit={(event) => void submitAppStore(event)} className="space-y-2">
                <Input aria-label="Issuer ID" placeholder="Issuer ID" value={field("issuerId")} onChange={set("issuerId")} />
                <Input aria-label="Key ID" placeholder="Key ID" value={field("keyId")} onChange={set("keyId")} />
                <Textarea aria-label=".p8 private key" rows={4} placeholder="-----BEGIN PRIVATE KEY-----"
                  value={field("privateKey")} onChange={set("privateKey")} />
                <Input aria-label="Upload .p8 file" type="file" accept=".p8,.pem,.txt" onChange={onFilePasted("privateKey")} />
                <Button type="submit" size="sm" disabled={busy === "appstore"}>Connect</Button>
              </form>
            ) : (
              <div className="mt-auto flex gap-2">
                <Button size="sm" variant={appstore ? "outline" : "default"}
                  onClick={() => { setError(""); setOpen("appstore"); }}>
                  {appstore ? "Reconnect" : "Connect"}
                </Button>
                {appstore ? (
                  <Button size="sm" variant="ghost" disabled={busy === "appstore"}
                    onClick={() => void disconnect("appstore")}>
                    Disconnect
                  </Button>
                ) : null}
              </div>
            )}
            {appstore && apps.appstore.length > 0 ? (
              <ul className="mt-2 space-y-1 text-sm">
                {apps.appstore.map((app) => (
                  <li key={app.id} className="flex items-center justify-between gap-2">
                    <Link href={auditHref(app)} className="underline-offset-4 hover:underline">{app.name}</Link>
                    <span className="text-muted-foreground">
                      v{app.version || "-"}{app.average_rating != null ? ` - ${app.average_rating}*` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="flex h-full flex-col gap-3 p-5">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-semibold">Google Play</h3>
              <Badge variant={play ? "success" : "secondary"}>{play ? "Connected" : "Not connected"}</Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              {play ? play.account_name : "Play Console -> API access -> a service account's JSON key."}
            </p>
            {open === "play" ? (
              <form onSubmit={(event) => void submitPlay(event)} className="space-y-2">
                <Textarea aria-label="Service account JSON" rows={4} placeholder='{"type": "service_account", ...}'
                  value={field("playJson")} onChange={set("playJson")} />
                <Input aria-label="Upload service-account JSON" type="file" accept=".json" onChange={onFilePasted("playJson")} />
                <Button type="submit" size="sm" disabled={busy === "play"}>Connect</Button>
              </form>
            ) : (
              <div className="mt-auto flex gap-2">
                <Button size="sm" variant={play ? "outline" : "default"}
                  onClick={() => { setError(""); setOpen("play"); }}>
                  {play ? "Reconnect" : "Connect"}
                </Button>
                {play ? (
                  <Button size="sm" variant="ghost" disabled={busy === "play"} onClick={() => void disconnect("play")}>
                    Disconnect
                  </Button>
                ) : null}
              </div>
            )}
            {play ? (
              <>
                <form onSubmit={(event) => void addPackage(event)} className="flex gap-2">
                  <Input aria-label="Android package name" placeholder="com.example.app" value={field("packageName")}
                    onChange={set("packageName")} className="flex-1" />
                  <Button type="submit" size="sm" variant="outline" disabled={busy === "play-app"}>Add app</Button>
                </form>
                <p className="text-xs text-muted-foreground">
                  Google Play has no &quot;list all my apps&quot; API — add each package name once.
                </p>
                {apps.play.length > 0 ? (
                  <ul className="space-y-1 text-sm">
                    {apps.play.map((app) => (
                      <li key={app.package_name} className="flex items-center justify-between gap-2">
                        <Link href={auditHref(app)} className="underline-offset-4 hover:underline">
                          {app.package_name}
                        </Link>
                        <span className="text-muted-foreground">
                          v{app.version_name || "-"}{app.average_rating != null ? ` - ${app.average_rating}*` : ""}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </>
            ) : null}
          </CardContent>
        </Card>
      </div>
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </section>
  );
}
