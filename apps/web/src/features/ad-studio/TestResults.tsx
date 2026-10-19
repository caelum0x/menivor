"use client";

import * as React from "react";
import { ExternalLink, Loader2, RefreshCw, Square, Trophy, WandSparkles } from "lucide-react";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { LogResultForm } from "./LogResultForm";
import { PLATFORM_LABEL, pct, when, type AdTest, type LogResultInput, type TestAd, type TestPost } from "./publish-api";
import { safeServerText } from "@/src/shared/errors";
import { ErrorText, errorMessage } from "./shared";

export interface TestActions {
  onCheck: (test: AdTest) => Promise<void>;
  onStop: (test: AdTest) => Promise<void>;
  onRemake: (test: AdTest, acceptLowConfidence: boolean) => Promise<void>;
  onLog: (ad: TestAd, input: LogResultInput) => Promise<void>;
}

const POST_BADGE: Record<string, { label: string; variant: BadgeVariant }> = {
  pending: { label: "Scheduled", variant: "secondary" },
  publishing: { label: "Posting", variant: "default" },
  processing: { label: "Processing", variant: "default" },
  published: { label: "Live", variant: "success" },
  failed: { label: "Failed", variant: "destructive" },
  canceled: { label: "Canceled", variant: "outline" },
};

function PostLine({ post }: { post: TestPost }) {
  const badge = POST_BADGE[post.status] ?? { label: post.status, variant: "outline" as BadgeVariant };
  return (
    <li className="flex flex-wrap items-center gap-2 text-xs">
      <span className="w-20 font-medium">{PLATFORM_LABEL[post.platform] ?? post.platform}</span>
      <Badge variant={badge.variant}>{badge.label}</Badge>
      {post.status === "pending" && post.scheduled_at ? (
        <span className="text-muted-foreground">{when(post.scheduled_at)}</span>
      ) : null}
      {post.url ? (
        <a href={post.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
          View post <ExternalLink className="h-3 w-3" aria-hidden />
        </a>
      ) : null}
      {post.error ? <span className="text-destructive">{safeServerText(post.error, "This post could not go out.")}</span> : null}
    </li>
  );
}

function Numbers({ ad }: { ad: TestAd }) {
  const m = ad.metrics;
  if (!m) {
    return ad.logged ? (
      <p className="text-xs text-muted-foreground">
        Logged: {ad.logged.views.toLocaleString()} views on {ad.logged.platform}
        {ad.logged.retention_pct ? `, ${ad.logged.retention_pct}% watched` : ""}. Ranked at the next check.
      </p>
    ) : (
      <p className="text-xs text-muted-foreground">No numbers yet.</p>
    );
  }
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
      <div><dt className="text-muted-foreground">Views</dt><dd className="font-medium">{(m.views ?? 0).toLocaleString()}</dd></div>
      <div><dt className="text-muted-foreground">Watched on average</dt><dd className="font-medium">{pct(m.avg_watch_frac)}</dd></div>
      <div><dt className="text-muted-foreground">Watched to the end</dt><dd className="font-medium">{pct(m.completion_rate)}</dd></div>
      <div><dt className="text-muted-foreground">Engagement</dt><dd className="font-medium">{pct(m.engagement_rate)}</dd></div>
      {m.source === "logged" ? <p className="col-span-full text-muted-foreground">From the numbers you logged.</p> : null}
    </dl>
  );
}

function AdRow({ ad, test, actions }: { ad: TestAd; test: AdTest; actions: TestActions }) {
  return (
    <li className={`space-y-2 rounded-md border p-3 ${ad.is_winner ? "border-success" : "border-border"}`}>
      <div className="flex flex-wrap items-start gap-3">
        {ad.poster_url ? (
          <img src={ad.poster_url} alt="" loading="lazy" className="h-20 w-12 shrink-0 rounded object-cover" />
        ) : null}
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            {ad.rank ? <span className="text-sm font-semibold">#{ad.rank}</span> : null}
            {ad.is_winner ? (
              <Badge variant="success"><Trophy className="mr-1 h-3 w-3" aria-hidden /> Winner</Badge>
            ) : null}
            <span className="text-xs text-muted-foreground">{ad.angle_label} · {ad.format} · {ad.aspect}</span>
          </div>
          {ad.hook ? <p className="text-sm">{ad.hook}</p> : null}
          <Numbers ad={ad} />
        </div>
      </div>
      {ad.posts.length ? <ul className="space-y-1">{ad.posts.map((p, i) => <PostLine key={`${p.platform}-${i}`} post={p} />)}</ul> : null}
      {test.mode === "manual" && !test.stopped ? (
        <LogResultForm initial={ad.logged} onSubmit={(input) => actions.onLog(ad, input)} />
      ) : null}
    </li>
  );
}

function statusVariant(test: AdTest): BadgeVariant {
  if (test.stopped) return "outline";
  if (test.status === "winner_ready" || test.status === "remade") return "success";
  if (test.status === "inconclusive") return "destructive";
  return "default";
}

function TestCard({ test, actions }: { test: AdTest; actions: TestActions }) {
  const [busy, setBusy] = React.useState<"" | "check" | "stop" | "remake">("");
  const [error, setError] = React.useState("");
  const run = (kind: typeof busy, fn: () => Promise<void>) => async () => {
    setBusy(kind);
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };
  const settled = ["winner_ready", "remade", "inconclusive", "cap_reached"].includes(test.status) || test.stopped;
  const remake = () => {
    if (!test.conclusive && !window.confirm("The numbers did not separate clearly. Remake this ad anyway?")) return Promise.resolve();
    return actions.onRemake(test, !test.conclusive);
  };
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={statusVariant(test)}>{test.status_label}</Badge>
            <span className="text-xs text-muted-foreground">
              {test.mode === "publish"
                ? `Posting to ${test.platforms.map((p) => PLATFORM_LABEL[p] ?? p).join(", ")}`
                : "Posted by you"}
              {test.started_at ? ` · started ${when(test.started_at)}` : ""}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {!settled ? (
              <Button size="sm" variant="outline" onClick={run("check", () => actions.onCheck(test))} disabled={busy !== ""}>
                {busy === "check" ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />} Check now
              </Button>
            ) : null}
            {!settled ? (
              <Button size="sm" variant="ghost" onClick={run("stop", () => actions.onStop(test))} disabled={busy !== ""}>
                <Square aria-hidden /> Stop test
              </Button>
            ) : null}
            {test.can_remake ? (
              <Button size="sm" onClick={run("remake", remake)} disabled={busy !== ""}>
                {busy === "remake" ? <Loader2 className="animate-spin" aria-hidden /> : <WandSparkles aria-hidden />} Remake winner
              </Button>
            ) : null}
          </div>
        </div>
        {test.check_due_at && !settled ? (
          <p className="text-sm text-muted-foreground">Results are read on {when(test.check_due_at)}. Check now shows an early read.</p>
        ) : null}
        {test.note ? <p className="text-sm text-muted-foreground" role="status">{test.note}</p> : null}
        {test.explanation?.headline && test.explanation.confidence !== "none" ? (
          <div className="rounded-md bg-secondary/40 p-3 text-sm">
            <p className="font-medium">
              {test.early_read && !settled ? "Early read: " : ""}
              {test.explanation.headline}
            </p>
            <ul className="mt-1 list-disc pl-5 text-muted-foreground">
              {test.explanation.reasons.map((r) => <li key={r}>{r}</li>)}
              {test.explanation.caveats.map((c) => <li key={c}>{c}</li>)}
            </ul>
          </div>
        ) : null}
        {test.remake ? (
          <p className="text-sm text-muted-foreground">
            Remade with {test.remake.variant_ids.length} new hook{test.remake.variant_ids.length === 1 ? "" : "s"}: the new ads are in the
            Ads list below and can go into the next test when they finish rendering.
          </p>
        ) : null}
        <ErrorText message={error} />
        <ul className="space-y-2">{test.ads.map((ad) => <AdRow key={ad.variant_id} ad={ad} test={test} actions={actions} />)}</ul>
      </CardContent>
    </Card>
  );
}

export function TestResults({ tests, actions }: { tests: AdTest[]; actions: TestActions }) {
  if (tests.length === 0) return null;
  return (
    <div className="space-y-4">
      {tests.map((test) => <TestCard key={test.batch_id} test={test} actions={actions} />)}
    </div>
  );
}
