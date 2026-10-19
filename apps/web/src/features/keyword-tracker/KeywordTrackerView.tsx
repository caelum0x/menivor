"use client";

/**
 * Keyword tracker (Menivor Growth phase 2): daily top-50 App Store rank per
 * tracked keyword, cached history, 7/30-day change. App Store only — the
 * Google Play Developer API has no public keyword-rank endpoint.
 */

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, Search } from "lucide-react";
import { useAuth } from "@/components/auth/clerk-safe";
import { signInHref } from "@/lib/auth-redirect";
import { useApiToken } from "@/lib/use-api-token";
import { useMyWorkspaces } from "@/lib/use-my-workspaces";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getStoredDeviceApiKey } from "@/src/shared/device/session";
import { friendlyErrorMessage, isSignedOutError } from "@/src/shared/errors/friendly";
import { listAppStoreApps } from "@/app/settings/integrations/_lib/api";
import { addKeyword, listKeywords, refreshKeyword, removeKeyword, type KeywordTrackerOverview } from "./api";
import { AddKeywordForm, type ConnectedApp } from "./AddKeywordForm";
import { KeywordRow } from "./KeywordRow";

type LoadState = "loading" | "ready" | "error" | "signed_out";

const KEYWORDS_PATH = "/keywords";

export function KeywordTrackerView() {
  const { isLoaded, isSignedIn } = useAuth();
  const getApiToken = useApiToken();
  const { workspaces } = useMyWorkspaces();
  const [state, setState] = React.useState<LoadState>("loading");
  const [overview, setOverview] = React.useState<KeywordTrackerOverview | null>(null);
  const [connectedApps, setConnectedApps] = React.useState<readonly ConnectedApp[]>([]);
  const [error, setError] = React.useState("");
  // Keywords themselves are personal, but an Apple Search Ads connection is
  // workspace-scoped (Settings > Integrations); default to the caller's
  // first workspace, same auto-select Settings > SEO uses, so popularity
  // shows up without needing its own picker on this page.
  const workspaceId = workspaces[0]?.id;

  const load = React.useCallback(async () => {
    try {
      const token = await getApiToken();
      const next = await listKeywords(workspaceId, { token });
      setOverview(next);
      setState("ready");
      // Best-effort: a creator with no connected App Store Connect account
      // (or whose key only reaches zero apps) just gets the manual-entry field.
      listAppStoreApps({ token })
        .then(({ apps }) => {
          const withIds = apps
            .filter((a) => Boolean(a.id))
            .map((a) => ({ id: a.id as string, name: a.name ?? "" }));
          setConnectedApps(withIds);
        })
        .catch(() => {});
    } catch (err) {
      if (isSignedOutError(err)) {
        setState("signed_out");
        return;
      }
      setError(friendlyErrorMessage(err, "Your tracked keywords could not be loaded."));
      setState("error");
    }
  }, [getApiToken, workspaceId]);

  React.useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn && !getStoredDeviceApiKey()) {
      setState("signed_out");
      return;
    }
    void load();
  }, [isLoaded, isSignedIn, load]);

  const add = async (input: { appId: string; term: string; appName: string; country: string }) => {
    const token = await getApiToken();
    const keyword = await addKeyword(input, { token });
    setOverview((current) =>
      current ? { ...current, keywords: [...current.keywords, keyword] } : current,
    );
  };

  const refresh = async (id: string) => {
    const token = await getApiToken();
    const keyword = await refreshKeyword(id, { token });
    setOverview((current) =>
      current ? { ...current, keywords: current.keywords.map((k) => (k.id === id ? keyword : k)) } : current,
    );
  };

  const remove = async (id: string) => {
    const token = await getApiToken();
    await removeKeyword(id, { token });
    setOverview((current) =>
      current ? { ...current, keywords: current.keywords.filter((k) => k.id !== id) } : current,
    );
  };

  if (state === "loading") return <KeywordTrackerSkeleton />;

  if (state === "signed_out") {
    return (
      <section className="glass-strong mx-auto max-w-xl rounded-3xl p-8 text-center">
        <h2 className="text-2xl font-semibold tracking-tight">Sign in to track keywords</h2>
        <Button asChild size="lg" className="neu-primary mt-6">
          <Link href={signInHref(KEYWORDS_PATH)}>Sign in</Link>
        </Button>
      </section>
    );
  }

  if (state === "error" || !overview) {
    return (
      <div className="glass flex items-start gap-3 rounded-2xl p-6">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
        <div>
          <p className="font-medium">Your tracked keywords could not be loaded</p>
          <p className="text-sm text-muted-foreground">{error}</p>
          <Button className="mt-3" variant="outline" size="sm" onClick={() => window.location.reload()}>
            Try again
          </Button>
        </div>
      </div>
    );
  }

  const atLimit = overview.keywords.length >= overview.limit;

  return (
    <div className="space-y-6">
      <section className="glass rounded-2xl p-5">
        <h2 className="mb-1 text-sm font-medium text-muted-foreground">Track a keyword</h2>
        <p className="mb-3 text-sm text-muted-foreground">
          Paste an App Store app id (from its apps.apple.com URL) and a search term. A daily check reads its
          top-50 rank from the public App Store search — no sign-in to Apple required.
        </p>
        <AddKeywordForm disabled={atLimit} connectedApps={connectedApps} onSubmit={add} />
        <p className="mt-2 text-xs text-muted-foreground" data-testid="keyword-limit">
          {overview.keywords.length} / {overview.limit} keywords tracked
          {atLimit && !overview.paid ? (
            <>
              {" "}
              ·{" "}
              <Link href="/billing" className="underline-offset-4 hover:underline">
                Upgrade to track more
              </Link>
            </>
          ) : null}
        </p>
      </section>

      {overview.keywords.length === 0 ? (
        <EmptyState />
      ) : (
        <section className="glass rounded-2xl p-5">
          <h2 className="mb-2 text-sm font-medium text-muted-foreground">Your tracked keywords</h2>
          <ul className="divide-y divide-border">
            {overview.keywords.map((keyword) => (
              <KeywordRow key={keyword.id} keyword={keyword} onRefresh={refresh} onRemove={remove} />
            ))}
          </ul>
        </section>
      )}
      <p className="text-xs text-muted-foreground">
        Ranks update once a day by themselves.{" "}
        {overview.apple_ads_connected ? (
          "Popularity (Apple's own Search Popularity index) is shown next to each keyword above."
        ) : (
          <>
            Popularity needs a connected Apple Search Ads account —{" "}
            <Link href="/settings/integrations" className="underline-offset-4 hover:underline">
              connect one in Settings
            </Link>
            .
          </>
        )}
      </p>
    </div>
  );
}

function EmptyState() {
  return (
    <section className="glass-strong mx-auto max-w-xl rounded-3xl p-8 text-center">
      <Search className="mx-auto size-10 text-primary" aria-hidden />
      <h2 className="mt-4 text-2xl font-semibold tracking-tight">See where you rank</h2>
      <p className="mt-2 text-muted-foreground">
        Add a keyword above. Menivor checks your App Store rank for it every day and charts the trend.
      </p>
    </section>
  );
}

function KeywordTrackerSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true">
      <Skeleton className="h-40 w-full rounded-2xl" />
      <Skeleton className="h-56 w-full rounded-2xl" />
    </div>
  );
}
