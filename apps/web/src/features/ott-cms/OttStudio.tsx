"use client";

import * as React from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { formatCredits, getStudio, packageTitle, parseCredits, publishAll, setPublished, updateChannel, updateTitle, type Credit, type OttChannel, type OttTitle, type PublishAllResult } from "./api";
import { UploadPanel } from "./UploadPanel";
import { PlanUsage } from "@/src/features/ott-plans";
import { StudioSales } from "@/src/features/ott-checkout";
import { StudioAds } from "@/src/features/ott-ads";
import { StudioLive } from "@/src/features/ott-live-chat";
import { StudioLinear } from "@/src/features/ott-linear";
import { AnalyticsPanel } from "@/src/features/ott-analytics";
import { AiPanel } from "@/src/features/ott-ai";
import { ottSurfaceLive } from "@/src/features/ott-player/flags";

/** One button makes the channel; then each title can be renamed, shown or hidden. */
export function OttStudio() {
  const getApiToken = useApiToken();
  const [channel, setChannel] = React.useState<OttChannel | null>(null);
  const [result, setResult] = React.useState<PublishAllResult | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      setChannel(await getStudio({ token: await getApiToken() }));
    } catch (err) {
      setError(friendlyErrorMessage(err, "Your channel could not load."));
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function act(fn: (token: string | undefined) => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn(await getApiToken());
      await load();
    } catch (err) {
      setError(friendlyErrorMessage(err, "That did not save."));
    } finally {
      setBusy(false);
    }
  }

  async function onPublishAll() {
    setBusy(true);
    setError("");
    try {
      const done = await publishAll({ token: await getApiToken() });
      setResult(done);
      setChannel(done.channel);
    } catch (err) {
      setError(friendlyErrorMessage(err, "The channel could not be published."));
    } finally {
      setBusy(false);
    }
  }

  if (!channel) return error ? <p role="alert">{error}</p> : <p className="text-sm text-muted-foreground">Loading</p>;
  return (
    <div className="space-y-6">
      {ottSurfaceLive("plans") ? <PlanUsage /> : null}
      {ottSurfaceLive("commerce") ? <StudioSales titles={channel.titles} /> : null}
      {ottSurfaceLive("ads") ? <StudioAds titles={channel.titles} /> : null}
      {ottSurfaceLive("live") ? <StudioLive /> : null}
      {ottSurfaceLive("fast") ? <StudioLinear titles={channel.titles} /> : null}
      {ottSurfaceLive("analytics") ? <AnalyticsPanel /> : null}
      {ottSurfaceLive("ai") ? <AiPanel titles={channel.titles} /> : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={busy} onClick={() => void onPublishAll()}>Publish my finished reels as a channel</Button>
        {channel.status === "published" ? (
          <Link className="text-sm underline" href={channel.storefront_path}>Open my channel</Link>
        ) : null}
      </div>
      {result ? (
        <p aria-live="polite" className="text-sm">
          {`${result.published.length} titles live in ${result.seconds.toFixed(1)} s.`}
          {result.held.length ? ` ${result.held.length} held: ${result.held.map((h) => h.reason).join("; ")}.` : ""}
        </p>
      ) : null}
      <label className="block text-sm">
        Channel name
        <input className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2" defaultValue={channel.title}
          maxLength={80} onBlur={(e) => void act((token) => updateChannel({ title: e.target.value }, { token }))} />
      </label>
      <UploadPanel onDone={() => void load()} />
      <ul className="space-y-3">
        {channel.titles.map((title) => (
          <TitleRow key={title.id} title={title} busy={busy}
            onPackage={() => void act((token) => packageTitle(title.id, { token }))}
            onRename={(name) => void act((token) => updateTitle(title.id, { title: name }, { token }))}
            onCredits={(credits) => void act((token) => updateTitle(title.id, { credits }, { token }))}
            onToggle={() => void act((token) => setPublished(title.id, title.status !== "published", { token }))} />
        ))}
      </ul>
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </div>
  );
}

function TitleRow({ title, busy, onRename, onToggle, onPackage, onCredits }: Readonly<{
  title: OttTitle;
  busy: boolean;
  onPackage: () => void;
  onRename: (name: string) => void;
  onToggle: () => void;
  onCredits: (credits: Credit[]) => void;
}>) {
  return (
    <li className="space-y-2 rounded-xl border border-border p-2">
    <div className="flex items-center gap-3">
      {title.artwork_url ? <img className="h-16 w-9 rounded object-cover" src={title.artwork_url} alt="" /> : null}
      <label className="flex-1 text-sm">
        <span className="sr-only">Title</span>
        <input className="w-full rounded border border-border bg-background px-2 py-1" defaultValue={title.title} maxLength={120}
          onBlur={(e) => e.target.value !== title.title && onRename(e.target.value)} />
      </label>
      <span className="text-xs text-muted-foreground">{title.status === "hidden" && title.hidden_reason === "takedown" ? "paused by a report" : title.status}</span>
      {title.source_job_id && (title.package_status === "none" || title.package_status === "failed") ? (
        <Button size="sm" variant="outline" disabled={busy} onClick={onPackage}>Prepare streaming</Button>
      ) : (
        <span className="text-xs text-muted-foreground">{title.package_status === "ready" ? "streaming ready" : title.package_status === "queued" ? "preparing" : ""}</span>
      )}
      <Button size="sm" variant="outline" disabled={busy || title.hidden_reason === "takedown"} onClick={onToggle}>
        {title.status === "published" ? "Hide" : "Publish"}
      </Button>
    </div>
    <label className="block text-xs text-muted-foreground">
      Cast and crew, one per line: name, role
      <textarea className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm" rows={2}
        defaultValue={formatCredits(title.credits)}
        onBlur={(e) => e.target.value !== formatCredits(title.credits) && onCredits(parseCredits(e.target.value))} />
    </label>
    </li>
  );
}
