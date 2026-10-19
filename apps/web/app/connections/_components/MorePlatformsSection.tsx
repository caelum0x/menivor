"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, CalendarClock, Globe, RefreshCw, Send } from "lucide-react";
import type { Job } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { rememberPendingProvider } from "@/components/connections/oauth-state";
import type { RequestOptions } from "@/src/shared/api";
import {
  EXTENDED_STATE_PREFIX,
  chooseTarget,
  connectBluesky,
  disconnectPlatform,
  errorText,
  getPlatforms,
  refreshTargets,
  startConnect,
  type ExtendedPlatform,
  type PlatformRecord,
  type PlatformsOverview,
} from "../_lib/publishing-api";
import { ExtendedPlatformCard } from "./ExtendedPlatformCard";
import { PostElsewhereDialog } from "./PostElsewhereDialog";

export interface MorePlatformsSectionProps {
  getOptions: () => Promise<RequestOptions>;
  /** The caller's finished reels, newest first. */
  jobs: readonly Job[];
  /** Bumped by the page after an OAuth callback so the list refreshes. */
  reloadKey: number;
  onNotice: (kind: "success" | "error", text: string) => void;
}

type LoadState = "loading" | "ready" | "error";

/**
 * Facebook Pages, LinkedIn, X, Threads, Pinterest and Bluesky: connect, choose
 * where to post, and post or schedule a finished reel to several at once.
 */
export function MorePlatformsSection({ getOptions, jobs, reloadKey, onNotice }: Readonly<MorePlatformsSectionProps>) {
  const [overview, setOverview] = React.useState<PlatformsOverview | null>(null);
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [loadError, setLoadError] = React.useState("");
  const [busy, setBusy] = React.useState<ExtendedPlatform | null>(null);
  const [cardErrors, setCardErrors] = React.useState<Readonly<Partial<Record<ExtendedPlatform, string>>>>({});
  const [dialogOpen, setDialogOpen] = React.useState(false);

  const load = React.useCallback(async () => {
    setStatus((s) => (s === "ready" ? s : "loading"));
    setLoadError("");
    try {
      setOverview(await getPlatforms(await getOptions()));
      setStatus("ready");
    } catch (err) {
      setLoadError(errorText(err, "Couldn't load the other platforms."));
      setStatus("error");
    }
  }, [getOptions]);

  React.useEffect(() => {
    void load();
  }, [load, reloadKey]);

  const replaceRecord = React.useCallback((record: PlatformRecord) => {
    setOverview((prev) =>
      prev
        ? { ...prev, platforms: prev.platforms.map((p) => (p.platform === record.platform ? record : p)) }
        : prev,
    );
  }, []);

  const run = React.useCallback(
    async (platform: ExtendedPlatform, action: () => Promise<void>) => {
      setBusy(platform);
      setCardErrors((prev) => ({ ...prev, [platform]: undefined }));
      try {
        await action();
      } catch (err) {
        setCardErrors((prev) => ({ ...prev, [platform]: errorText(err, "Something went wrong.") }));
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  const onConnect = (platform: ExtendedPlatform, organization: boolean) =>
    void run(platform, async () => {
      const info = await startConnect(platform, organization, await getOptions());
      rememberPendingProvider(info.state, `${EXTENDED_STATE_PREFIX}${platform}`);
      window.location.assign(info.authorize_url);
    });

  const onConnectBluesky = (handle: string, appPassword: string, pds: string) =>
    void run("bluesky", async () => {
      replaceRecord(await connectBluesky(handle, appPassword, pds, await getOptions()));
      onNotice("success", "Connected Bluesky.");
    });

  const onChooseTarget = (platform: ExtendedPlatform, targetId: string) =>
    void run(platform, async () => {
      replaceRecord(await chooseTarget(platform, targetId, await getOptions()));
    });

  const onRefreshTargets = (platform: ExtendedPlatform) =>
    void run(platform, async () => {
      replaceRecord(await refreshTargets(platform, await getOptions()));
    });

  const onDisconnect = (platform: ExtendedPlatform) =>
    void run(platform, async () => {
      await disconnectPlatform(platform, await getOptions());
      await load();
      onNotice("success", "Disconnected.");
    });

  const ready = overview?.platforms.filter((p) => p.state === "connected") ?? [];

  return (
    <section className="mt-10 space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <Globe className="size-5 text-primary" aria-hidden />
            More platforms
          </h2>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Post finished reels to Facebook Pages, LinkedIn, X, Threads, Pinterest and Bluesky, now or on a
            schedule. Each platform gets a caption that fits its limits.
          </p>
        </div>
        <div className="flex gap-2">
          <Button asChild variant="outline" size="sm">
            <Link href="/connections/queue">
              <CalendarClock className="size-4" aria-hidden /> Queue
            </Link>
          </Button>
          <Button
            size="sm"
            disabled={ready.length === 0 || jobs.length === 0}
            title={
              ready.length === 0
                ? "Connect one of these platforms first."
                : jobs.length === 0
                  ? "Finish a reel first."
                  : undefined
            }
            onClick={() => setDialogOpen(true)}
          >
            <Send className="size-4" aria-hidden /> Post to these platforms
          </Button>
        </div>
      </div>

      {status === "loading" && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="space-y-3 p-5">
                <Skeleton className="h-10 w-40" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-9 w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {status === "error" && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex flex-col items-start gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
            <p className="flex items-start gap-2 text-sm">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
              {loadError}
            </p>
            <Button variant="outline" size="sm" onClick={() => void load()}>
              <RefreshCw className="size-4" aria-hidden /> Try again
            </Button>
          </CardContent>
        </Card>
      )}

      {status === "ready" && overview && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {overview.platforms.map((record) => (
            <ExtendedPlatformCard
              key={record.platform}
              record={record}
              busy={busy === record.platform}
              error={cardErrors[record.platform]}
              publishingEnabled={overview.publishing_enabled}
              onConnect={onConnect}
              onConnectBluesky={onConnectBluesky}
              onChooseTarget={onChooseTarget}
              onRefreshTargets={onRefreshTargets}
              onDisconnect={onDisconnect}
            />
          ))}
        </div>
      )}

      <PostElsewhereDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        platforms={ready}
        jobs={jobs}
        getOptions={getOptions}
      />
    </section>
  );
}
