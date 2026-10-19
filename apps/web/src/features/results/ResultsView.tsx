"use client";

/**
 * Results: which hooks and styles win, from the real numbers Menivor reads for
 * every posted reel. Reels published through a connected account are tracked
 * by themselves; anything else is one pasted link away. Nothing is estimated:
 * a number a platform does not share is left out, never shown as 0.
 */

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, BarChart3, RefreshCw } from "lucide-react";
import { useAuth } from "@/components/auth/clerk-safe";
import { authorizeConnection } from "@/lib/api";
import { signInHref } from "@/lib/auth-redirect";
import { useApiToken } from "@/lib/use-api-token";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getStoredDeviceApiKey } from "@/src/shared/device/session";
import { friendlyErrorMessage, isSignedOutError } from "@/src/shared/errors/friendly";
import {
  getResults,
  syncResults,
  trackPostLink,
  typePostNumbers,
  untrackPost,
  type Results,
  type ResultsPlatform,
  type TypedNumbers,
} from "./api";
import { PasteLink } from "./PasteLink";
import { PostList } from "./PostList";
import { ViewsChart } from "./ViewsChart";
import { WinnerCard } from "./WinnerCard";

type LoadState = "loading" | "ready" | "error" | "signed_out";

const RESULTS_PATH = "/performance";

export function ResultsView() {
  const { isLoaded, isSignedIn } = useAuth();
  const getApiToken = useApiToken();
  const [state, setState] = React.useState<LoadState>("loading");
  const [results, setResults] = React.useState<Results | null>(null);
  const [error, setError] = React.useState("");
  const [syncing, setSyncing] = React.useState(false);

  const sync = React.useCallback(async () => {
    setSyncing(true);
    try {
      const token = await getApiToken();
      setResults(await syncResults({ token }));
    } catch {
      // The stored numbers are already on screen; the next scheduled read catches up.
    } finally {
      setSyncing(false);
    }
  }, [getApiToken]);

  React.useEffect(() => {
    if (!isLoaded) return undefined;
    // Signed out with no guest session in this browser: every call would 401.
    if (!isSignedIn && !getStoredDeviceApiKey()) {
      setState("signed_out");
      return undefined;
    }
    let active = true;
    void (async () => {
      try {
        const token = await getApiToken();
        const first = await getResults({ token });
        if (!active) return;
        setResults(first);
        setState("ready");
        if (first.tracking > 0) void sync();
      } catch (err) {
        if (!active) return;
        if (isSignedOutError(err)) {
          setState("signed_out");
          return;
        }
        setError(friendlyErrorMessage(err, "Your results could not be loaded."));
        setState("error");
      }
    })();
    return () => {
      active = false;
    };
  }, [getApiToken, isLoaded, isSignedIn, sync]);

  const withToken = React.useCallback(
    async (run: (token: string | undefined) => Promise<Results>) => {
      const token = await getApiToken();
      setResults(await run(token));
    },
    [getApiToken],
  );

  const addLink = (url: string) => withToken((token) => trackPostLink(url, { token }));
  const typeNumbers = (postId: string, numbers: TypedNumbers) =>
    withToken((token) => typePostNumbers(postId, numbers, { token }));
  const remove = (postId: string) => withToken((token) => untrackPost(postId, { token }));

  if (state === "loading") return <ResultsSkeleton />;
  if (state === "signed_out") {
    return (
      <section className="glass-strong mx-auto max-w-xl rounded-3xl p-8 text-center">
        <h2 className="text-2xl font-semibold tracking-tight">Sign in to see your results</h2>
        <Button asChild size="lg" className="neu-primary mt-6">
          <Link href={signInHref(RESULTS_PATH)}>Sign in</Link>
        </Button>
      </section>
    );
  }
  if (state === "error" || !results) {
    return (
      <div className="glass flex items-start gap-3 rounded-2xl p-6">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
        <div>
          <p className="font-medium">Your results could not be loaded</p>
          <p className="text-sm text-muted-foreground">{error}</p>
          <Button className="mt-3" variant="outline" size="sm" onClick={() => window.location.reload()}>
            Try again
          </Button>
        </div>
      </div>
    );
  }

  if (results.tracking === 0) {
    return <EmptyState platforms={results.platforms} onAddLink={addLink} />;
  }

  return (
    <div className="space-y-6">
      <ReconnectPrompts platforms={results.platforms} />
      {results.winner ? (
        <WinnerCard winner={results.winner} styles={results.styles} />
      ) : (
        <ReadingNumbers syncing={syncing} />
      )}
      <ViewsChart series={results.series} />
      <PostList posts={results.posts} onTypeNumbers={typeNumbers} onRemove={remove} />
      <section className="glass-subtle rounded-2xl p-5">
        <h2 className="mb-1 text-sm font-medium">Posted somewhere else?</h2>
        <p className="mb-3 text-sm text-muted-foreground">
          Paste the link and Menivor keeps its numbers up to date.
        </p>
        <PasteLink onSubmit={addLink} />
      </section>
      <div className="flex items-center justify-end gap-2 text-xs text-muted-foreground">
        {syncing ? <RefreshCw className="size-3 animate-spin" aria-hidden /> : null}
        {syncing ? "Checking for new numbers..." : "Numbers update by themselves every few hours."}
      </div>
    </div>
  );
}

function useConnect(): [(platform: string) => Promise<void>, string, string] {
  const getApiToken = useApiToken();
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const connect = async (platform: string) => {
    setBusy(platform);
    setError("");
    try {
      const token = await getApiToken();
      const info = await authorizeConnection(platform, { token });
      if (!info.authorize_url) throw new Error("no authorize url");
      window.location.assign(info.authorize_url);
    } catch (err) {
      setError(friendlyErrorMessage(err, "That connection could not be started. Try again."));
      setBusy("");
    }
  };
  return [connect, busy, error];
}

function EmptyState({
  platforms,
  onAddLink,
}: Readonly<{ platforms: readonly ResultsPlatform[]; onAddLink: (url: string) => Promise<void> }>) {
  const [connect, busy, error] = useConnect();
  const [pasting, setPasting] = React.useState(false);
  const anyConnected = platforms.some((p) => p.connected);
  const tiktok = platforms.find((p) => p.platform === "tiktok");
  // No TikTok app on this server: the connect button would only fail, so the
  // paste field is the one action.
  const canConnect = tiktok?.can_connect !== false;

  return (
    <section className="glass-strong mx-auto max-w-xl rounded-3xl p-8 text-center">
      <BarChart3 className="mx-auto size-10 text-primary" aria-hidden />
      <h2 className="mt-4 text-2xl font-semibold tracking-tight">See which hooks win</h2>
      <p className="mt-2 text-muted-foreground">
        {anyConnected
          ? "Reels you publish from Menivor show up here by themselves. Posted one yourself? Paste its link."
          : canConnect
            ? "Connect your account once. Menivor reads the views of every reel you post and shows what works."
            : "Paste the link to a reel you posted. Menivor reads its numbers and shows what works."}
      </p>
      <div className="mt-6">
        {anyConnected || pasting || !canConnect ? (
          <PasteLink onSubmit={onAddLink} autoFocus={pasting} />
        ) : (
          <>
            <Button
              size="lg"
              className="neu-primary w-full sm:w-auto"
              disabled={busy !== ""}
              onClick={() => void connect(tiktok?.platform ?? "tiktok")}
            >
              {busy ? "Opening TikTok..." : "Connect TikTok"}
            </Button>
            <button
              type="button"
              onClick={() => setPasting(true)}
              className="mt-4 block w-full text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
            >
              Or paste a post link
            </button>
          </>
        )}
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </section>
  );
}

function ReconnectPrompts({ platforms }: Readonly<{ platforms: readonly ResultsPlatform[] }>) {
  const [connect, busy, error] = useConnect();
  const needs = platforms.filter((p) => p.connected && p.needs_reconnect);
  if (needs.length === 0) return null;
  return (
    <div className="space-y-2">
      {needs.map((p) => (
        <div
          key={p.platform}
          className="glass-subtle flex flex-col gap-3 rounded-2xl p-4 sm:flex-row sm:items-center sm:justify-between"
        >
          <p className="text-sm">{p.note}</p>
          {p.reconnect_here && p.can_connect !== false ? (
            <Button size="sm" disabled={busy !== ""} onClick={() => void connect(p.platform)}>
              {busy === p.platform ? "Opening..." : `Reconnect ${p.label}`}
            </Button>
          ) : (
            <Button asChild size="sm" variant="outline">
              <Link href="/connections">Reconnect {p.label}</Link>
            </Button>
          )}
        </div>
      ))}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function ReadingNumbers({ syncing }: Readonly<{ syncing: boolean }>) {
  return (
    <section className="glass-strong rounded-3xl p-6 sm:p-8">
      <p className="text-sm font-medium text-primary">Almost there</p>
      <h2 className="mt-2 text-2xl font-semibold tracking-tight">
        {syncing ? "Reading your numbers..." : "Your winners show up once the first numbers are in"}
      </h2>
      <p className="mt-2 text-muted-foreground">
        Platforms share views a little while after a post goes live. This page fills in by itself.
      </p>
    </section>
  );
}

function ResultsSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true">
      <Skeleton className="h-48 w-full rounded-3xl" />
      <Skeleton className="h-44 w-full rounded-2xl" />
      <Skeleton className="h-32 w-full rounded-2xl" />
    </div>
  );
}
