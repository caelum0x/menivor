"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth, UserButton } from "@/components/auth/clerk-safe";
import {
  AlertTriangle,
  CheckCircle2,
  Plug,
  RefreshCw,
  Send,
  X,
} from "lucide-react";
import {
  ApiError,
  authorizeConnection,
  completeConnect,
  disconnectConnection,
  listConnections,
  listJobs,
  publishJobTo,
} from "@/lib/api";
import {
  isFailedState,
  isTerminalState,
  SOCIAL_CONNECTION_PROVIDERS,
  type Connection,
  type Job,
  type PublishResult,
  type SocialProvider,
} from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ProviderCard } from "@/components/connections/ProviderCard";
import { PublishReelDialog } from "@/components/connections/PublishReelDialog";
import { providerLabel } from "@/components/connections/providers";
import {
  rememberPendingProvider,
  takePendingProvider,
} from "@/components/connections/oauth-state";
import { MorePlatformsSection } from "./_components/MorePlatformsSection";
import { PLATFORM_LABELS } from "./_components/platform-meta";
import {
  EXTENDED_STATE_PREFIX,
  errorText,
  finishConnect,
  type ExtendedPlatform,
} from "./_lib/publishing-api";
import { MenivorMark } from "@/components/brand/MenivorMark";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

interface Notice {
  kind: "success" | "error";
  text: string;
}

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/** Immutably add/remove a provider slug in a Set of pending slugs. */
function withToggled(
  set: ReadonlySet<string>,
  value: string,
  present: boolean,
): Set<string> {
  const next = new Set(set);
  if (present) next.add(value);
  else next.delete(value);
  return next;
}

export default function ConnectionsPage() {
  const { isLoaded } = useAuth();
  const getApiToken = useApiToken();

  const [status, setStatus] = React.useState<LoadState>("loading");
  const [connections, setConnections] = React.useState<readonly Connection[]>(
    [],
  );
  const [jobs, setJobs] = React.useState<readonly Job[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [notice, setNotice] = React.useState<Notice | null>(null);

  const [connecting, setConnecting] = React.useState<ReadonlySet<string>>(
    new Set(),
  );
  const [disconnecting, setDisconnecting] = React.useState<ReadonlySet<string>>(
    new Set(),
  );
  const [cardErrors, setCardErrors] = React.useState<
    Readonly<Record<string, string>>
  >({});
  const [publishOpen, setPublishOpen] = React.useState(false);
  // Bumped after an extended-platform OAuth callback so that section reloads.
  const [extendedReloadKey, setExtendedReloadKey] = React.useState(0);

  const getOptions = React.useCallback(
    async () => ({ token: await getApiToken() }),
    [getApiToken],
  );

  const showNotice = React.useCallback(
    (kind: "success" | "error", text: string) => setNotice({ kind, text }),
    [],
  );

  // Guards the one-shot OAuth-callback handler so it runs at most once.
  const callbackHandled = React.useRef(false);

  const load = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = await getApiToken();
      const [conns, jobList] = await Promise.all([
        listConnections({ token }),
        listJobs({ token }),
      ]);
      setConnections(conns);
      setJobs(jobList);
      setStatus("ready");
    } catch (err) {
      setErrorMessage(
        errorMessageOf(err, "Something went wrong loading your connections."),
      );
      setStatus("error");
    }
  }, [getApiToken]);

  React.useEffect(() => {
    if (isLoaded) void load();
  }, [isLoaded, load]);

  // Finish an OAuth connect when the provider redirects back to this page with
  // `?code=&state=`. The provider is recovered from an explicit `provider` query
  // param or the state->provider bridge stored before the redirect. The query is
  // stripped from the URL first so a refresh/replay can't re-run the exchange.
  React.useEffect(() => {
    if (!isLoaded || callbackHandled.current) return;
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    const denied = params.get("error");
    if (denied && state) {
      callbackHandled.current = true;
      const pending = takePendingProvider(state) ?? "";
      window.history.replaceState(null, "", "/connections");
      const platform = pending.startsWith(EXTENDED_STATE_PREFIX)
        ? PLATFORM_LABELS[pending.slice(EXTENDED_STATE_PREFIX.length) as ExtendedPlatform]
        : pending
          ? providerLabel(pending)
          : "the platform";
      setNotice({
        kind: "error",
        text: `The connection to ${platform} was not completed${
          params.get("error_description") ? `: ${params.get("error_description")}` : "."
        }`,
      });
      return;
    }
    if (!code || !state) return;

    callbackHandled.current = true;
    const provider =
      params.get("provider") ?? takePendingProvider(state) ?? undefined;
    window.history.replaceState(null, "", "/connections");

    if (provider?.startsWith(EXTENDED_STATE_PREFIX)) {
      const platform = provider.slice(EXTENDED_STATE_PREFIX.length) as ExtendedPlatform;
      const label = PLATFORM_LABELS[platform] ?? platform;
      void (async () => {
        try {
          const record = await finishConnect(code, state, await getOptions());
          setNotice({
            kind: "success",
            text:
              record.state === "needs_target"
                ? `Connected ${label}. Choose where to post below.`
                : `Connected ${label}.`,
          });
        } catch (err) {
          setNotice({
            kind: "error",
            text: errorText(err, `Failed to finish connecting ${label}.`),
          });
        } finally {
          setExtendedReloadKey((k) => k + 1);
        }
      })();
      return;
    }

    if (!provider) {
      setNotice({
        kind: "error",
        text: "Couldn't tell which account you were connecting. Please try again.",
      });
      return;
    }

    void (async () => {
      try {
        const token = await getApiToken();
        const refreshed = await completeConnect(provider, code, state, {
          token,
        });
        setConnections(refreshed);
        setNotice({
          kind: "success",
          text: `Connected ${providerLabel(provider)}.`,
        });
      } catch (err) {
        setNotice({
          kind: "error",
          text: errorMessageOf(
            err,
            `Failed to finish connecting ${providerLabel(provider)}.`,
          ),
        });
      }
    })();
  }, [isLoaded, getApiToken, getOptions]);

  const setCardError = React.useCallback(
    (provider: string, message: string) => {
      setCardErrors((prev) => ({ ...prev, [provider]: message }));
    },
    [],
  );

  const clearCardError = React.useCallback((provider: string) => {
    setCardErrors((prev) => {
      if (!(provider in prev)) return prev;
      const next = { ...prev };
      delete next[provider];
      return next;
    });
  }, []);

  const handleConnect = React.useCallback(
    async (provider: SocialProvider) => {
      const key = String(provider);
      clearCardError(key);
      setConnecting((prev) => withToggled(prev, key, true));
      try {
        const token = await getApiToken();
        const info = await authorizeConnection(provider, { token });
        if (!info.authorize_url) {
          throw new ApiError("The provider returned no authorize URL.", 0);
        }
        // Persist which provider this `state` belongs to, then hand the browser
        // off to the provider's consent screen.
        rememberPendingProvider(info.state, provider);
        window.location.assign(info.authorize_url);
        // Navigation unmounts the page; no state reset needed on success.
      } catch (err) {
        setConnecting((prev) => withToggled(prev, key, false));
        setCardError(
          key,
          errorMessageOf(err, `Couldn't start connecting ${providerLabel(provider)}.`),
        );
      }
    },
    [getApiToken, clearCardError, setCardError],
  );

  const handleDisconnect = React.useCallback(
    async (provider: SocialProvider) => {
      const key = String(provider);
      clearCardError(key);
      setDisconnecting((prev) => withToggled(prev, key, true));
      try {
        const token = await getApiToken();
        await disconnectConnection(provider, { token });
        setConnections((prev) => prev.filter((c) => c.provider !== provider));
        setNotice({
          kind: "success",
          text: `Disconnected ${providerLabel(provider)}.`,
        });
      } catch (err) {
        setCardError(
          key,
          errorMessageOf(err, `Couldn't disconnect ${providerLabel(provider)}.`),
        );
      } finally {
        setDisconnecting((prev) => withToggled(prev, key, false));
      }
    },
    [getApiToken, clearCardError, setCardError],
  );

  const handlePublish = React.useCallback(
    async (
      jobId: string,
      provider: SocialProvider,
      caption?: string,
    ): Promise<PublishResult> => {
      const token = await getApiToken();
      return publishJobTo(jobId, provider, caption, { token });
    },
    [getApiToken],
  );

  // Providers to render: the known allow-list, in order, plus any connected
  // provider the backend added that the client doesn't yet know about.
  const providersToShow = React.useMemo<SocialProvider[]>(() => {
    const known = new Set<string>(SOCIAL_CONNECTION_PROVIDERS);
    const extras = connections
      .map((c) => c.provider)
      .filter((p) => !known.has(String(p)));
    const seen = new Set<string>();
    const ordered: SocialProvider[] = [];
    for (const p of [...SOCIAL_CONNECTION_PROVIDERS, ...extras]) {
      const key = String(p);
      if (!seen.has(key)) {
        seen.add(key);
        ordered.push(p);
      }
    }
    return ordered;
  }, [connections]);

  const connectionByProvider = React.useMemo(() => {
    const map = new Map<string, Connection>();
    for (const c of connections) map.set(String(c.provider), c);
    return map;
  }, [connections]);

  const connectedProviders = React.useMemo<SocialProvider[]>(
    () => connections.filter((c) => c.connected).map((c) => c.provider),
    [connections],
  );

  const completedJobs = React.useMemo(
    () =>
      jobs.filter((j) => isTerminalState(j.state) && !isFailedState(j.state)),
    [jobs],
  );

  const canPublish = connectedProviders.length > 0 && completedJobs.length > 0;

  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
          <div className="flex items-center gap-3">
            <Button asChild variant="outline" size="sm">
              <Link href="/reels">Your reels</Link>
            </Button>
            <Button
              size="sm"
              disabled={!canPublish}
              title={
                canPublish
                  ? undefined
                  : "Connect an account and finish a reel to publish."
              }
              onClick={() => setPublishOpen(true)}
            >
              <Send className="size-4" aria-hidden /> Publish a reel
            </Button>
            <UserButton />
          </div>
        </div>
      </header>

      <section className="container py-8">
        <div className="mb-6 flex items-end justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
              <Plug className="size-6 text-primary" aria-hidden />
              Connections
            </h1>
            <p className="text-sm text-muted-foreground">
              Link your social accounts, then publish a finished reel straight to
              them. We never show or store your login — only a secure token, kept
              encrypted on our servers.
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load()}
            disabled={status === "loading"}
          >
            <RefreshCw
              className={status === "loading" ? "size-4 animate-spin" : "size-4"}
              aria-hidden
            />
            Refresh
          </Button>
        </div>

        {notice && (
          <NoticeBanner notice={notice} onDismiss={() => setNotice(null)} />
        )}

        {status === "loading" && <ConnectionsSkeleton />}

        {status === "error" && (
          <ErrorPanel message={errorMessage} onRetry={() => void load()} />
        )}

        {status === "ready" && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {providersToShow.map((provider) => (
              <ProviderCard
                key={String(provider)}
                provider={provider}
                connection={connectionByProvider.get(String(provider))}
                connecting={connecting.has(String(provider))}
                disconnecting={disconnecting.has(String(provider))}
                error={cardErrors[String(provider)]}
                onConnect={(p) => void handleConnect(p)}
                onDisconnect={(p) => void handleDisconnect(p)}
              />
            ))}
          </div>
        )}

        {status === "ready" && (
          <MorePlatformsSection
            getOptions={getOptions}
            jobs={completedJobs}
            reloadKey={extendedReloadKey}
            onNotice={showNotice}
          />
        )}
      </section>

      <PublishReelDialog
        open={publishOpen}
        onClose={() => setPublishOpen(false)}
        connectedProviders={connectedProviders}
        jobs={completedJobs}
        onPublish={handlePublish}
      />
    </main>
  );
}

function NoticeBanner({
  notice,
  onDismiss,
}: Readonly<{ notice: Notice; onDismiss: () => void }>) {
  const isError = notice.kind === "error";
  return (
    <div
      className={
        isError
          ? "mb-6 flex items-start justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4"
          : "mb-6 flex items-start justify-between gap-3 rounded-lg border border-success/40 bg-success/5 p-4"
      }
      role="status"
    >
      <div className="flex items-start gap-3">
        {isError ? (
          <AlertTriangle
            className="mt-0.5 size-5 shrink-0 text-destructive"
            aria-hidden
          />
        ) : (
          <CheckCircle2
            className="mt-0.5 size-5 shrink-0 text-success"
            aria-hidden
          />
        )}
        <p className="text-sm">{notice.text}</p>
      </div>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Dismiss"
        onClick={onDismiss}
      >
        <X className="size-4" aria-hidden />
      </Button>
    </div>
  );
}

function ConnectionsSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 3 }).map((_, i) => (
        <Card key={i}>
          <CardContent className="space-y-4 p-5">
            <div className="flex items-center gap-3">
              <Skeleton className="size-10 rounded-lg" />
              <div className="space-y-2">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-3 w-32" />
              </div>
            </div>
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-2/3" />
            <Skeleton className="h-9 w-full rounded-md" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function ErrorPanel({
  message,
  onRetry,
}: Readonly<{ message: string; onRetry: () => void }>) {
  return (
    <Card className="border-destructive/40 bg-destructive/5">
      <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <AlertTriangle
            className="mt-0.5 size-5 shrink-0 text-destructive"
            aria-hidden
          />
          <div>
            <p className="font-medium">Couldn&apos;t load your connections</p>
            <p className="text-sm text-muted-foreground">{message}</p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="size-4" aria-hidden /> Try again
        </Button>
      </CardContent>
    </Card>
  );
}
