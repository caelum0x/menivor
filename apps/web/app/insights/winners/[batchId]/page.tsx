"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/clerk-safe";
import { AlertTriangle, ArrowLeft, BarChart3, Info, RefreshCw, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  checkLoopNow,
  configureLoop,
  errorMessageOf,
  formatWhen,
  getLoop,
  LoopSettingsCard,
  LoopTimeline,
  MODE_LABELS,
  relativeTime,
  remakeWinner,
  statusLabel,
  VariantRanking,
  WhyItWon,
  type LoopConfigInput,
  type LoopDetail,
} from "@/src/features/insights";

type LoadState = "loading" | "ready" | "error";
type Action = "idle" | "saving" | "checking" | "remaking";

/** One project's winner loop: settings, ranking, why it won, remake, timeline. */
export default function WinnerLoopDetailPage() {
  const params = useParams<{ batchId: string }>();
  const batchId = String(params?.batchId ?? "");
  const router = useRouter();
  const { getToken, isLoaded } = useAuth();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [detail, setDetail] = React.useState<LoopDetail | null>(null);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [action, setAction] = React.useState<Action>("idle");
  const [actionError, setActionError] = React.useState("");
  const [actionNotice, setActionNotice] = React.useState("");
  const [confirmLowConfidence, setConfirmLowConfidence] = React.useState(false);

  const token = React.useCallback(async () => (await getToken()) ?? undefined, [getToken]);

  const load = React.useCallback(async () => {
    if (!batchId) return;
    setStatus("loading");
    setErrorMessage("");
    try {
      setDetail(await getLoop(batchId, { token: await token() }));
      setStatus("ready");
    } catch (err) {
      setErrorMessage(errorMessageOf(err, "Something went wrong loading this project."));
      setStatus("error");
    }
  }, [batchId, token]);

  React.useEffect(() => {
    if (isLoaded) void load();
  }, [isLoaded, load]);

  const run = async (kind: Action, fn: () => Promise<void>) => {
    setAction(kind);
    setActionError("");
    setActionNotice("");
    try {
      await fn();
    } catch (err) {
      setActionError(errorMessageOf(err, "That did not work. Please try again."));
    } finally {
      setAction("idle");
    }
  };

  const save = (input: LoopConfigInput) =>
    run("saving", async () => {
      setDetail(await configureLoop(batchId, input, { token: await token() }));
      setActionNotice(input.mode === "off" ? "Loop turned off." : "Loop settings saved.");
    });

  const checkNow = () =>
    run("checking", async () => {
      setDetail(await checkLoopNow(batchId, { token: await token() }));
      setActionNotice("Numbers refreshed from the platforms.");
    });

  const remake = () =>
    run("remaking", async () => {
      const lowConfidence = Boolean(detail && !detail.conclusive);
      if (lowConfidence && !confirmLowConfidence) {
        setConfirmLowConfidence(true);
        return;
      }
      const result = await remakeWinner(batchId, lowConfidence, { token: await token() });
      setConfirmLowConfidence(false);
      setActionNotice(
        result.enqueue_failures.length
          ? `${result.job_ids.length - result.enqueue_failures.length} of ${result.job_ids.length} new variants started; the rest were refunded.`
          : `3 new variants are rendering (${result.credits} credits).`,
      );
      await load();
    });

  if (status === "loading") {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (status === "error" || !detail) {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
            <div>
              <p className="font-medium">Couldn&apos;t load this project</p>
              <p className="text-sm text-muted-foreground">{errorMessage}</p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="size-4" aria-hidden /> Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  const hasWinner = Boolean(detail.winner_job_id);
  const canRemake = hasWinner && !detail.remake_batch_id;
  const busy = action !== "idle";

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Link
          href="/insights/winners"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" aria-hidden /> All loops
        </Link>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{detail.title}</h1>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              <span>Round {detail.generation}</span>
              <Badge variant={detail.status === "winner_ready" ? "success" : "secondary"}>
                {statusLabel(detail.status)}
              </Badge>
              {detail.configured && <Badge variant="outline">{MODE_LABELS[detail.mode]}</Badge>}
              {detail.check_due_at && (detail.status === "live" || detail.status === "measuring") && (
                <span>
                  Next check {formatWhen(detail.check_due_at)} ({relativeTime(detail.check_due_at)})
                </span>
              )}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {detail.configured && (
              <Button variant="outline" size="sm" onClick={() => void checkNow()} disabled={busy}>
                <BarChart3 aria-hidden /> {action === "checking" ? "Reading numbers" : "Check now"}
              </Button>
            )}
            {canRemake && (
              <Button size="sm" onClick={() => void remake()} disabled={busy}>
                <Sparkles aria-hidden />
                {action === "remaking"
                  ? "Starting remake"
                  : confirmLowConfidence
                    ? `Confirm remake (${detail.remake_cost_credits} credits)`
                    : `Remake winner (${detail.remake_cost_credits} credits)`}
              </Button>
            )}
            {detail.remake_batch_id && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => router.push(`/insights/winners/${encodeURIComponent(detail.remake_batch_id)}`)}
              >
                Open next round
              </Button>
            )}
          </div>
        </div>
      </div>

      {confirmLowConfidence && (
        <p className="rounded-md border border-border bg-secondary/30 p-3 text-sm">
          This winner is low-confidence ({detail.ranking_reason || "the numbers were close"}).
          Click confirm to spend {detail.remake_cost_credits} credits remaking it anyway.
        </p>
      )}
      {detail.note && (
        <p className="flex items-start gap-2 rounded-md border border-border bg-secondary/30 p-3 text-sm text-muted-foreground">
          <Info className="mt-0.5 size-4 shrink-0" aria-hidden /> {detail.note}
        </p>
      )}
      {actionError && (
        <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
          {actionError}
        </p>
      )}
      {actionNotice && (
        <p role="status" className="rounded-md border border-success/40 bg-success/5 p-3 text-sm">
          {actionNotice}
        </p>
      )}
      {detail.remake_hooks.length > 0 && (
        <Card>
          <CardContent className="space-y-1 p-5 text-sm">
            <p className="font-medium">New hooks in the next round</p>
            <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
              {detail.remake_hooks.map((hook) => (
                <li key={hook}>{hook}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <LoopSettingsCard detail={detail} saving={action === "saving"} onSave={(input) => void save(input)} />
        <WhyItWon explanation={detail.explanation} earlyRead={detail.early_read} hasWinner={hasWinner} />
      </div>

      <VariantRanking
        variants={detail.variants}
        usesRetention={detail.uses_retention}
        rankingReason={detail.ranking_reason}
      />

      <LoopTimeline
        items={detail.timeline}
        lineage={detail.lineage}
        onSelectBatch={(id) => router.push(`/insights/winners/${encodeURIComponent(id)}`)}
      />
    </div>
  );
}
