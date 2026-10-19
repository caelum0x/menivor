"use client";

import * as React from "react";
import { Search } from "lucide-react";
import { SettingsHeader } from "@/components/settings/SettingsHeader";
import { WorkspacePicker } from "@/components/settings/WorkspacePicker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useApiToken } from "@/lib/use-api-token";
import { useMyWorkspaces } from "@/lib/use-my-workspaces";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import {
  addRankKeywords,
  connectSeo,
  disconnectSeo,
  getAuditStatus,
  getSeoOverview,
  listKeywordResearch,
  refreshRankTracker,
  removeRankKeyword,
  researchKeywords,
  runSiteAudit,
  validateOpenSeoKey,
  type KeywordResearchRow,
  type Scope,
  type SeoOverview,
} from "./_lib/api";

type LoadState = "loading" | "ready" | "error";
type ConnectedSeoOverview = Extract<SeoOverview, { connected: true }>;

/**
 * Settings -> SEO (Menivor Growth): connect a workspace's own OpenSEO account,
 * run a basic site audit, research keywords for their niche, and track a
 * handful of target keywords' rank. Every OpenSEO call here spends the
 * workspace's own OpenSEO credits and runs only when a button below is
 * clicked -- nothing is scheduled automatically.
 */
export default function SeoPage() {
  const getApiToken = useApiToken();
  const { workspaces } = useMyWorkspaces();
  const [workspaceId, setWorkspaceId] = React.useState<string | null>(null);
  const [data, setData] = React.useState<SeoOverview | null>(null);
  const [research, setResearch] = React.useState<readonly KeywordResearchRow[]>([]);
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState<string>("");

  React.useEffect(() => {
    const first = workspaces[0];
    if (workspaceId === null && first) setWorkspaceId(first.id);
  }, [workspaceId, workspaces]);

  const scope: Scope = React.useMemo(() => ({ workspaceId }), [workspaceId]);

  const load = React.useCallback(async () => {
    setError("");
    try {
      const token = (await getApiToken()) ?? "";
      const overview = await getSeoOverview(scope, { token });
      setData(overview);
      if (overview.connected) {
        setResearch((await listKeywordResearch(scope, { token })).keywords);
      }
      setStatus("ready");
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not load SEO."));
      setStatus("error");
    }
  }, [getApiToken, scope]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const run = React.useCallback(
    async (key: string, fn: () => Promise<unknown>) => {
      setBusy(key);
      setError("");
      try {
        await fn();
        await load();
      } catch (err) {
        setError(friendlyErrorMessage(err, "That didn't work."));
      } finally {
        setBusy("");
      }
    },
    [load],
  );

  return (
    <main className="min-h-dvh">
      <SettingsHeader active="/settings/seo" />
      <section className="container py-10">
        <div className="mx-auto max-w-3xl space-y-8">
          <div className="space-y-4">
            <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
              <Search className="size-7 text-primary" aria-hidden />
              SEO
            </h1>
            <p className="text-sm text-muted-foreground">
              Connect your own OpenSEO account for a site audit, keyword research and rank tracking on a
              handful of target keywords, right inside Menivor. Every audit, research and rank-refresh click
              spends your own OpenSEO credits -- nothing here runs on its own.
            </p>
            <WorkspacePicker workspaces={workspaces} selectedId={workspaceId} onSelect={setWorkspaceId} />
          </div>

          {status === "loading" ? <Skeleton className="h-40 w-full" aria-busy /> : null}

          {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}

          {status === "ready" && data && !data.connected ? (
            <ConnectCard
              busy={busy === "connect"}
              onConnect={(apiKey, domain) => run("connect", () => connectSeo(apiKey, domain, scope))}
            />
          ) : null}

          {status === "ready" && data && data.connected ? (
            <>
              <Card>
                <CardHeader className="flex flex-row items-center justify-between">
                  <CardTitle>OpenSEO connection</CardTitle>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy === "disconnect"}
                    onClick={() => run("disconnect", () => disconnectSeo(scope))}
                  >
                    Disconnect
                  </Button>
                </CardHeader>
                <CardContent className="space-y-1 text-sm text-muted-foreground">
                  <p>Key: {data.token_hint || "connected"}</p>
                  <p>Project: {data.domain || data.project_id || "none yet"}</p>
                  {data.last_error ? <p className="text-destructive">{data.last_error}</p> : null}
                </CardContent>
              </Card>

              <AuditCard
                audit={data.latest_audit}
                busy={busy}
                canRun={Boolean(data.domain || data.project_id)}
                onRun={() => run("audit", () => runSiteAudit(scope))}
                onRefresh={(id) => run("audit-status", () => getAuditStatus(id, scope))}
              />

              <ResearchCard
                rows={research}
                busy={busy === "research"}
                onResearch={(seeds) => run("research", () => researchKeywords(seeds, scope))}
              />

              <RankTrackerCard
                keywords={data.tracked_keywords}
                limit={data.tracked_keyword_limit}
                busy={busy}
                onAdd={(keyword) => run("rank-add", () => addRankKeywords([keyword], "us", scope))}
                onRemove={(id) => run("rank-remove", () => removeRankKeyword(id, scope))}
                onRefresh={() => run("rank-refresh", () => refreshRankTracker(scope))}
              />
            </>
          ) : null}
        </div>
      </section>
    </main>
  );
}

function ConnectCard({
  busy,
  onConnect,
}: Readonly<{ busy: boolean; onConnect: (apiKey: string, domain: string) => void }>) {
  const [apiKey, setApiKey] = React.useState("");
  const [domain, setDomain] = React.useState("");
  const [localError, setLocalError] = React.useState("");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Connect OpenSEO</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="seo-api-key">OpenSEO API key</Label>
          <Input
            id="seo-api-key"
            type="password"
            placeholder="oseo_..."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="seo-domain">Your site&apos;s domain</Label>
          <Input
            id="seo-domain"
            placeholder="example.com"
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
          />
        </div>
        {localError ? <p role="alert" className="text-sm text-destructive">{localError}</p> : null}
        <Button
          disabled={busy}
          onClick={() => {
            const problem = validateOpenSeoKey(apiKey);
            if (problem) {
              setLocalError(problem);
              return;
            }
            setLocalError("");
            onConnect(apiKey, domain);
          }}
        >
          {busy ? "Connecting..." : "Connect"}
        </Button>
      </CardContent>
    </Card>
  );
}

function AuditCard({
  audit,
  busy,
  canRun,
  onRun,
  onRefresh,
}: Readonly<{
  audit: ConnectedSeoOverview["latest_audit"];
  busy: string;
  canRun: boolean;
  onRun: () => void;
  onRefresh: (id: string) => void;
}>) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Site audit</CardTitle>
        <Button size="sm" disabled={busy === "audit" || !canRun} onClick={onRun}>
          {busy === "audit" ? "Starting..." : "Run audit"}
        </Button>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {!audit ? (
          <p className="text-muted-foreground">No audit yet. Running one spends OpenSEO credits.</p>
        ) : (
          <div className="flex items-center gap-3">
            <Badge variant={audit.status === "completed" ? "success" : "secondary"}>{audit.status}</Badge>
            {audit.score !== null ? <span>Score {audit.score}</span> : null}
            {audit.issues_count !== null ? <span>{audit.issues_count} issues</span> : null}
            {audit.status !== "completed" ? (
              <Button variant="outline" size="sm" disabled={busy === "audit-status"} onClick={() => onRefresh(audit.id)}>
                Check status
              </Button>
            ) : null}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ResearchCard({
  rows,
  busy,
  onResearch,
}: Readonly<{ rows: readonly KeywordResearchRow[]; busy: boolean; onResearch: (seeds: string[]) => void }>) {
  const [seed, setSeed] = React.useState("");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Keyword research</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <Input placeholder="seed keyword" value={seed} onChange={(e) => setSeed(e.target.value)} />
          <Button
            disabled={busy || !seed.trim()}
            onClick={() => {
              onResearch([seed]);
              setSeed("");
            }}
          >
            {busy ? "Researching..." : "Research"}
          </Button>
        </div>
        {rows.length > 0 ? (
          <ul className="space-y-1 text-sm">
            {rows.map((row) => (
              <li key={row.keyword} className="flex justify-between gap-2 text-muted-foreground">
                <span>{row.keyword}</span>
                <span>{row.volume ?? "?"} vol &middot; difficulty {row.difficulty ?? "?"}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">No research yet.</p>
        )}
      </CardContent>
    </Card>
  );
}

function RankTrackerCard({
  keywords,
  limit,
  busy,
  onAdd,
  onRemove,
  onRefresh,
}: Readonly<{
  keywords: ConnectedSeoOverview["tracked_keywords"];
  limit: number;
  busy: string;
  onAdd: (keyword: string) => void;
  onRemove: (id: string) => void;
  onRefresh: () => void;
}>) {
  const [keyword, setKeyword] = React.useState("");

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Rank tracker ({keywords.length}/{limit})</CardTitle>
        <Button
          variant="outline"
          size="sm"
          disabled={busy === "rank-refresh" || keywords.length === 0}
          onClick={onRefresh}
        >
          {busy === "rank-refresh" ? "Refreshing..." : "Refresh ranks"}
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {keywords.length < limit ? (
          <div className="flex gap-2">
            <Input placeholder="target keyword" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
            <Button
              disabled={busy === "rank-add" || !keyword.trim()}
              onClick={() => {
                onAdd(keyword);
                setKeyword("");
              }}
            >
              Add
            </Button>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            You&apos;re tracking the maximum of {limit} keywords. Remove one to add another.
          </p>
        )}
        {keywords.length > 0 ? (
          <ul className="space-y-1 text-sm">
            {keywords.map((k) => (
              <li key={k.id} className="flex items-center justify-between gap-2">
                <span>
                  {k.keyword} ({k.country.toUpperCase()}) -- rank {k.current_rank ?? "not checked"}
                  {k.change_7d ? ` (${k.change_7d > 0 ? "+" : ""}${k.change_7d})` : ""}
                </span>
                <Button variant="ghost" size="sm" onClick={() => onRemove(k.id)}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}
