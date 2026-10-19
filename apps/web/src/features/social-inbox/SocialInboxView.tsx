"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { AlertTriangle, ExternalLink, Inbox, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { rememberPendingProvider } from "@/components/connections/oauth-state";
import type { RequestOptions } from "@/src/shared/api";
import {
  PAGE_SIZE,
  authorizeInboxScopes,
  getInboxOverview,
  listThreads,
  syncInbox,
} from "./api";
import { errorMessageOf, formatCount, relativeTime } from "./format";
import { InboxFilters } from "./InboxFilters";
import { PlatformStatus } from "./PlatformStatus";
import { PostEngagement } from "./PostEngagement";
import { ThreadList } from "./ThreadList";
import { ThreadPanel } from "./ThreadPanel";
import type { InboxOverview, InboxPlatform, InboxThread, ThreadFilters } from "./types";
import { ActivityLog } from "./ActivityLog";
import { ApprovalQueue } from "./ApprovalQueue";
import { AutopilotSettings } from "./AutopilotSettings";
import { getAutopilot } from "./autopilot-api";
import { LeadsView } from "./LeadsView";

type InboxTab = "conversations" | "approvals" | "leads" | "autopilot" | "activity";

const TABS: readonly { key: InboxTab; label: string }[] = [
  { key: "conversations", label: "Conversations" },
  { key: "approvals", label: "Approvals" },
  { key: "leads", label: "Leads" },
  { key: "autopilot", label: "Autopilot" },
  { key: "activity", label: "Activity" },
];

const DEFAULT_FILTERS: ThreadFilters = { platform: "", postId: "", status: "needs_reply", kind: "" };

type LoadState = "loading" | "ready" | "error";

/** The social inbox: platform states, filters, conversations, reply panel, post counts. */
export function SocialInboxView() {
  const { getToken, isLoaded } = useAuth();
  const [overview, setOverview] = React.useState<InboxOverview | null>(null);
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [error, setError] = React.useState("");
  const [filters, setFilters] = React.useState<ThreadFilters>(DEFAULT_FILTERS);
  const [threads, setThreads] = React.useState<InboxThread[]>([]);
  const [total, setTotal] = React.useState(0);
  const [threadsLoading, setThreadsLoading] = React.useState(false);
  const [threadsError, setThreadsError] = React.useState("");
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [syncing, setSyncing] = React.useState(false);
  const [syncMessage, setSyncMessage] = React.useState("");
  const [reconnecting, setReconnecting] = React.useState<InboxPlatform | null>(null);
  const [tab, setTab] = React.useState<InboxTab>("conversations");
  const [badges, setBadges] = React.useState<{ approvals: number; leads: number }>({ approvals: 0, leads: 0 });

  const getOptions = React.useCallback(async (): Promise<RequestOptions> => {
    const token = (await getToken()) ?? undefined;
    return { token };
  }, [getToken]);

  const loadOverview = React.useCallback(async () => {
    setStatus((s) => (s === "ready" ? s : "loading"));
    setError("");
    try {
      setOverview(await getInboxOverview(await getOptions()));
      setStatus("ready");
    } catch (err) {
      setError(errorMessageOf(err, "Something went wrong loading your inbox."));
      setStatus("error");
    }
  }, [getOptions]);

  const loadThreads = React.useCallback(
    async (append = false, offset = 0) => {
      setThreadsLoading(true);
      setThreadsError("");
      try {
        const page = await listThreads(filters, offset, await getOptions());
        setThreads((prev) => (append ? [...prev, ...page.threads] : page.threads));
        setTotal(page.total);
      } catch (err) {
        setThreadsError(errorMessageOf(err, "Couldn't load conversations."));
      } finally {
        setThreadsLoading(false);
      }
    },
    [filters, getOptions],
  );

  React.useEffect(() => {
    if (isLoaded) void loadOverview();
  }, [isLoaded, loadOverview]);

  React.useEffect(() => {
    if (isLoaded) void loadThreads();
  }, [isLoaded, loadThreads]);

  const loadBadges = React.useCallback(async () => {
    try {
      const data = await getAutopilot(await getOptions());
      setBadges({ approvals: data.pending_approvals, leads: data.new_leads });
    } catch {
      // Counts are a convenience; the tabs still load their own data.
    }
  }, [getOptions]);

  React.useEffect(() => {
    if (isLoaded) void loadBadges();
  }, [isLoaded, loadBadges]);

  const onChanged = React.useCallback(() => {
    void loadOverview();
    void loadThreads();
    void loadBadges();
  }, [loadOverview, loadThreads, loadBadges]);

  const openThread = React.useCallback((threadId: string) => {
    setFilters({ ...DEFAULT_FILTERS, status: "all" });
    setSelectedId(threadId);
    setTab("conversations");
  }, []);

  const onSync = async () => {
    setSyncing(true);
    setSyncMessage("");
    try {
      const result = await syncInbox(await getOptions());
      setOverview(result);
      const s = result.sync;
      setSyncMessage(
        s ? `Checked ${s.synced} post${s.synced === 1 ? "" : "s"}${s.discovered ? `, found ${s.discovered} new` : ""}.` : "Synced.",
      );
      await loadThreads();
    } catch (err) {
      setSyncMessage(errorMessageOf(err, "Couldn't sync right now."));
    } finally {
      setSyncing(false);
    }
  };

  const onReconnect = async (platform: InboxPlatform, scopes: string) => {
    setReconnecting(platform);
    try {
      const info = await authorizeInboxScopes(platform, scopes, await getOptions());
      rememberPendingProvider(info.state, platform);
      window.location.assign(info.authorize_url);
    } catch (err) {
      setSyncMessage(errorMessageOf(err, "Couldn't start the reconnect."));
      setReconnecting(null);
    }
  };

  const onFilters = (next: ThreadFilters) => {
    setFilters(next);
    setSelectedId(null);
  };

  const appOnlyPosts = (overview?.posts ?? []).filter(
    (p) => p.kind === "post" && p.inbox_state === "not_offered" && (p.counts.platform_comments ?? 0) > 0,
  );
  const noPosts = overview !== null && overview.posts.filter((p) => p.kind === "post").length === 0;

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Inbox className="size-6 text-primary" aria-hidden />
            Inbox
          </h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Comments and messages on the posts Menivor published for you, in one place. Reply
            here where the platform allows it; otherwise copy the reply and open the post.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Button variant="outline" size="sm" onClick={() => void onSync()} disabled={syncing}>
            <RefreshCw className={syncing ? "size-4 animate-spin" : "size-4"} aria-hidden />
            {syncing ? "Checking..." : "Check now"}
          </Button>
          <span className="text-xs text-muted-foreground">
            {syncMessage || `Last checked ${relativeTime(overview?.last_synced_at)}`}
          </span>
        </div>
      </div>

      <div
        role="tablist"
        aria-label="Inbox sections"
        className="mb-6 flex flex-wrap gap-1 rounded-lg border border-border bg-secondary/40 p-1"
      >
        {TABS.map((t) => {
          const count = t.key === "approvals" ? badges.approvals : t.key === "leads" ? badges.leads : 0;
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
              className={
                tab === t.key
                  ? "flex items-center gap-2 rounded-md bg-background px-3 py-1.5 text-sm font-medium shadow-sm"
                  : "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground"
              }
            >
              {t.label}
              {count > 0 && (
                <span className="rounded-full bg-primary/15 px-1.5 py-0.5 text-xs tabular-nums text-primary">
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {tab === "approvals" && (
        <ApprovalQueue getOptions={getOptions} onChanged={onChanged} onOpenThread={openThread} />
      )}
      {tab === "leads" && <LeadsView getOptions={getOptions} onChanged={onChanged} onOpenThread={openThread} />}
      {tab === "autopilot" && <AutopilotSettings getOptions={getOptions} onChanged={onChanged} />}
      {tab === "activity" && <ActivityLog getOptions={getOptions} />}

      {tab === "conversations" && status === "loading" && (
        <div className="grid gap-3 md:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="space-y-3 p-4">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {tab === "conversations" && status === "error" && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
              <div>
                <p className="font-medium">Couldn&apos;t load your inbox</p>
                <p className="text-sm text-muted-foreground">{error}</p>
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={() => void loadOverview()}>
              <RefreshCw className="size-4" aria-hidden /> Try again
            </Button>
          </CardContent>
        </Card>
      )}

      {tab === "conversations" && status === "ready" && overview && (
        <div className="space-y-6">
          <PlatformStatus
            platforms={overview.platforms}
            needsReplyByPlatform={overview.totals.needs_reply_by_platform}
            reconnecting={reconnecting}
            onReconnect={(p, s) => void onReconnect(p, s)}
          />

          {!overview.sending_enabled && (
            <p className="rounded-md border border-border bg-secondary/40 px-4 py-3 text-sm">
              Sending replies from Menivor is not enabled for your account yet. You can read
              comments, get reply suggestions, and copy replies into the app.
            </p>
          )}

          {noPosts && (
            <Card>
              <CardContent className="p-6 text-sm text-muted-foreground">
                Nothing here yet. Once Menivor publishes a video to a connected account, its comments show
                up here within a few minutes.
              </CardContent>
            </Card>
          )}

          {appOnlyPosts.length > 0 && (
            <Card>
              <CardContent className="space-y-2 p-4 text-sm">
                <p className="font-medium">Comments you can only answer in the app</p>
                <p className="text-muted-foreground">
                  These platforms report how many comments a post has but do not let apps read or
                  reply to them.
                </p>
                <ul className="space-y-1">
                  {appOnlyPosts.map((p) => (
                    <li key={p.id} className="flex items-center justify-between gap-2">
                      <span className="truncate">
                        {p.platform_label}: {p.title || "Untitled post"} (
                        {formatCount(p.counts.platform_comments)} comments)
                      </span>
                      {p.url && (
                        <a
                          href={p.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex shrink-0 items-center gap-1 text-primary hover:underline"
                        >
                          Open <ExternalLink className="size-3.5" aria-hidden />
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          <InboxFilters filters={filters} posts={overview.posts} onChange={onFilters} />

          <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
            <div className="space-y-3">
              {threadsError && (
                <p className="text-sm text-destructive" role="alert">
                  {threadsError}
                </p>
              )}
              {threadsLoading && threads.length === 0 ? (
                <div className="space-y-2">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-16 w-full" />
                  ))}
                </div>
              ) : threads.length === 0 ? (
                <Card>
                  <CardContent className="p-6 text-sm text-muted-foreground">
                    {filters.status === "needs_reply"
                      ? "You're all caught up. No conversations are waiting for a reply."
                      : "No conversations match these filters."}
                  </CardContent>
                </Card>
              ) : (
                <>
                  <ThreadList threads={threads} selectedId={selectedId} onSelect={setSelectedId} />
                  {threads.length < total && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full"
                      disabled={threadsLoading}
                      onClick={() => void loadThreads(true, threads.length)}
                    >
                      {threadsLoading ? "Loading..." : `Load more (${total - threads.length} left)`}
                    </Button>
                  )}
                </>
              )}
            </div>
            <div>
              {selectedId ? (
                <ThreadPanel
                  key={selectedId}
                  threadId={selectedId}
                  getOptions={getOptions}
                  onChanged={onChanged}
                />
              ) : (
                threads.length > 0 && (
                  <Card>
                    <CardContent className="p-6 text-sm text-muted-foreground">
                      Pick a conversation to read it and reply.
                    </CardContent>
                  </Card>
                )
              )}
            </div>
          </div>

          <PostEngagement
            posts={overview.posts}
            onFilterPost={(postId) => onFilters({ ...filters, postId, status: "all" })}
          />
        </div>
      )}
    </>
  );
}

