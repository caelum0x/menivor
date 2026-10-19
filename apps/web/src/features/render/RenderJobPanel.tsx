"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Ban, Cpu, Download, Loader2, RefreshCw, Sparkles } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  advanceRender,
  cancelRender,
  getRender,
  listRenders,
  playableOutputs,
  startRender,
  type RenderJob,
} from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { safeServerText } from "@/src/shared/errors/friendly";

/** GPU backend used for product renders (hosted serverless workers). */
const RENDER_BACKEND = "runpod";
const RENDER_POLL_INTERVAL_MS = 3_000;
const PROMPT_MAX = 1_000;
const HISTORY_PAGE_SIZE = 10;
const TERMINAL_STATES = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

const ASPECTS = [
  { value: "9:16", label: "Vertical 9:16 (Reels, TikTok, Shorts)", width: 480, height: 832 },
  { value: "16:9", label: "Landscape 16:9 (YouTube)", width: 832, height: 480 },
  { value: "1:1", label: "Square 1:1 (feed)", width: 640, height: 640 },
] as const;

const DURATIONS = [3, 5, 8] as const;

/** Spend caps in micro-USD. The wallet holds the cap and charges only the actual cost. */
const BUDGETS = [
  { micros: 100_000, label: "$0.10" },
  { micros: 250_000, label: "$0.25" },
  { micros: 500_000, label: "$0.50" },
] as const;

const STATE_LABEL: Record<string, string> = {
  IN_QUEUE: "Queued",
  QUEUED: "Queued",
  IN_PROGRESS: "Rendering",
  RUNNING: "Rendering",
  COMPLETED: "Ready",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `render-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function messageOf(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

function isTerminal(job: RenderJob): boolean {
  return TERMINAL_STATES.has(job.state);
}

function stateLabel(state: string): string {
  return STATE_LABEL[state] ?? state.replace(/_/g, " ").toLowerCase();
}

function formatCost(micros: number): string {
  return `$${(Math.max(0, micros) / 1_000_000).toFixed(2)}`;
}

function formatWhen(value?: string | null): string {
  if (!value) return "";
  const t = Date.parse(value);
  return Number.isNaN(t) ? "" : new Date(t).toLocaleString();
}

/** Replace (or prepend) a job in the history list without mutating it. */
function upsertHistory(list: readonly RenderJob[], job: RenderJob): RenderJob[] {
  const exists = list.some((entry) => entry.id === job.id);
  if (!exists) return [job, ...list];
  return list.map((entry) => (entry.id === job.id ? { ...entry, ...job } : entry));
}

/** Start a wallet-metered async-GPU text-to-video render and follow it to a result. */
export function RenderJobPanel() {
  const { getToken } = useAuth();
  const [prompt, setPrompt] = React.useState("");
  const [aspect, setAspect] = React.useState<string>(ASPECTS[0].value);
  const [durationS, setDurationS] = React.useState<number>(DURATIONS[1]);
  const [budget, setBudget] = React.useState<number>(BUDGETS[0].micros);
  const [job, setJob] = React.useState<RenderJob | null>(null);
  const [history, setHistory] = React.useState<RenderJob[]>([]);
  const [historyStatus, setHistoryStatus] = React.useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [historyError, setHistoryError] = React.useState("");
  const [historyHasMore, setHistoryHasMore] = React.useState(false);
  const [historyLoadingMore, setHistoryLoadingMore] = React.useState(false);
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const inFlight = React.useRef(false);
  const pendingStart = React.useRef<{ signature: string; idempotencyKey: string } | null>(null);

  const terminal = job ? isTerminal(job) : false;

  const loadHistory = React.useCallback(async () => {
    setHistoryStatus((prev) => (prev === "ready" ? prev : "loading"));
    setHistoryError("");
    try {
      const token = (await getToken()) ?? undefined;
      const page = await listRenders({ limit: HISTORY_PAGE_SIZE, offset: 0, source: "render" }, { token });
      setHistory(page.jobs);
      setHistoryHasMore(page.hasMore);
      setHistoryStatus("ready");
    } catch (err) {
      setHistoryError(messageOf(err, "Couldn't load your render history."));
      setHistoryStatus("error");
    }
  }, [getToken]);

  const loadMoreHistory = React.useCallback(async () => {
    setHistoryLoadingMore(true);
    setHistoryError("");
    try {
      const token = (await getToken()) ?? undefined;
      const page = await listRenders(
        { limit: HISTORY_PAGE_SIZE, offset: history.length, source: "render" },
        { token },
      );
      setHistory((prev) => {
        const seen = new Set(prev.map((entry) => entry.id));
        return [...prev, ...page.jobs.filter((entry) => !seen.has(entry.id))];
      });
      setHistoryHasMore(page.hasMore && page.jobs.length > 0);
    } catch (err) {
      setHistoryError(messageOf(err, "Couldn't load older renders."));
    } finally {
      setHistoryLoadingMore(false);
    }
  }, [getToken, history.length]);

  React.useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  // Keep the history row for the active job in sync with its live status.
  React.useEffect(() => {
    if (job) setHistory((prev) => upsertHistory(prev, job));
  }, [job]);

  React.useEffect(() => {
    if (!job || terminal) return;
    const jobId = job.id;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const token = (await getToken()) ?? undefined;
          const updated = await getRender(jobId, { token, signal: controller.signal });
          setJob((current) => (current?.id === jobId ? updated : current));
        } catch (err) {
          if (controller.signal.aborted) return;
          setError(messageOf(err, "Failed to refresh render."));
        }
      })();
    }, RENDER_POLL_INTERVAL_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [getToken, job, terminal]);

  /** Runs one mutation at a time with shared busy/error handling. */
  const runExclusive = React.useCallback(
    async (fallback: string, action: (token: string | undefined) => Promise<void>) => {
      if (inFlight.current) return;
      inFlight.current = true;
      setBusy(true);
      setError("");
      try {
        const token = (await getToken()) ?? undefined;
        await action(token);
      } catch (err) {
        setError(messageOf(err, fallback));
      } finally {
        inFlight.current = false;
        setBusy(false);
      }
    },
    [getToken],
  );

  const onStart = React.useCallback(async () => {
    const trimmed = prompt.trim();
    if (!trimmed) return;
    const shape = ASPECTS.find((a) => a.value === aspect) ?? ASPECTS[0];
    const body = {
      backend: RENDER_BACKEND,
      spec: {
        prompt: trimmed,
        aspect: shape.value,
        width: shape.width,
        height: shape.height,
        duration_s: durationS,
      },
      max_cost_micros: budget,
      label: trimmed.slice(0, 200),
    };
    const signature = JSON.stringify(body);
    if (!pendingStart.current || pendingStart.current.signature !== signature) {
      pendingStart.current = { signature, idempotencyKey: newIdempotencyKey() };
    }
    const commandKey = pendingStart.current.idempotencyKey;
    await runExclusive("Failed to start the render.", async (token) => {
      const started = await startRender(body, { token, idempotencyKey: commandKey });
      pendingStart.current = null;
      setJob({ ...started, label: started.label || trimmed });
    });
  }, [aspect, budget, durationS, prompt, runExclusive]);

  const onCheckNow = React.useCallback(async () => {
    if (!job) return;
    await runExclusive("Failed to check the render.", async (token) => {
      setJob(await advanceRender(job.id, { token }));
    });
  }, [job, runExclusive]);

  const onCancel = React.useCallback(async () => {
    if (!job) return;
    await runExclusive("Failed to cancel the render.", async (token) => {
      setJob(await cancelRender(job.id, { token }));
    });
  }, [job, runExclusive]);

  const onOpenHistory = React.useCallback(
    async (id: string) => {
      await runExclusive("Failed to load that render.", async (token) => {
        setJob(await getRender(id, { token }));
      });
    },
    [runExclusive],
  );

  const budgetLabel = BUDGETS.find((b) => b.micros === budget)?.label ?? formatCost(budget);
  const pastRenders = history.filter((entry) => entry.id !== job?.id);
  const showHistory =
    historyStatus !== "ready" || pastRenders.length > 0 || historyHasMore;

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-4 py-5">
          <div className="flex items-center gap-2">
            <Cpu className="h-4 w-4 text-primary" aria-hidden />
            <h2 className="font-semibold">New render</h2>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="render-prompt">Prompt</Label>
            <Textarea
              id="render-prompt"
              placeholder="Prompt"
              value={prompt}
              maxLength={PROMPT_MAX}
              rows={3}
              onChange={(e) => setPrompt(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Describe the shot: subject, setting, camera move, lighting.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="render-aspect">Format</Label>
              <Select id="render-aspect" value={aspect} onChange={(e) => setAspect(e.target.value)}>
                {ASPECTS.map((a) => (
                  <option key={a.value} value={a.value}>
                    {a.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="render-duration">Length</Label>
              <Select
                id="render-duration"
                value={String(durationS)}
                onChange={(e) => setDurationS(Number(e.target.value))}
              >
                {DURATIONS.map((d) => (
                  <option key={d} value={d}>
                    {d} seconds
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="render-budget">Spend cap</Label>
              <Select
                id="render-budget"
                value={String(budget)}
                onChange={(e) => setBudget(Number(e.target.value))}
              >
                {BUDGETS.map((b) => (
                  <option key={b.micros} value={b.micros}>
                    Up to {b.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <Button onClick={() => void onStart()} disabled={busy || !prompt.trim()}>
            {busy ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Sparkles className="mr-1 h-4 w-4" aria-hidden />
            )}
            Start render ({budgetLabel} max)
          </Button>
          <p className="text-xs text-muted-foreground">
            The cap is held from your wallet and only the actual cost is charged. Failed or
            cancelled renders are refunded in full.
          </p>
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>

      {job && (
        <RenderResultCard
          job={job}
          busy={busy}
          onCheckNow={() => void onCheckNow()}
          onCancel={() => void onCancel()}
        />
      )}

      {showHistory && (
        <Card>
          <CardContent className="space-y-3 py-5">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">Your renders</h2>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void loadHistory()}
                disabled={historyStatus === "loading"}
                aria-label="Refresh render history"
              >
                <RefreshCw
                  className={historyStatus === "loading" ? "h-4 w-4 animate-spin" : "h-4 w-4"}
                  aria-hidden
                />
              </Button>
            </div>
            {historyStatus === "loading" && (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading your renders
              </p>
            )}
            {historyError && (
              <p className="text-sm text-destructive" role="alert">
                {historyError}
              </p>
            )}
            {historyStatus === "ready" && pastRenders.length === 0 && !historyHasMore && (
              <p className="text-sm text-muted-foreground">No earlier renders yet.</p>
            )}
            {pastRenders.length > 0 && (
              <ul className="divide-y divide-border">
                {pastRenders.map((entry) => (
                  <li key={entry.id} className="flex items-center justify-between gap-3 py-2">
                    <span className="min-w-0">
                      <span className="block truncate text-sm">
                        {entry.label || `Render ${entry.id.slice(0, 8)}`}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {[
                          stateLabel(entry.state),
                          formatWhen(entry.created_at),
                          entry.cost_micros > 0 ? formatCost(entry.cost_micros) : "",
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={() => void onOpenHistory(entry.id)}
                    >
                      Open
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            {historyHasMore && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => void loadMoreHistory()}
                disabled={historyLoadingMore}
              >
                {historyLoadingMore ? (
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
                ) : null}
                Load older renders
              </Button>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function RenderResultCard({
  job,
  busy,
  onCheckNow,
  onCancel,
}: Readonly<{
  job: RenderJob;
  busy: boolean;
  onCheckNow: () => void;
  onCancel: () => void;
}>) {
  const terminal = isTerminal(job);
  const completed = job.state === "COMPLETED";
  const failed = job.state === "FAILED";
  const progressPct = Math.round(Math.min(1, Math.max(0, job.progress)) * 100);
  const urls = playableOutputs(job);
  const hiddenOutputs =
    job.unusable_output_refs ?? Math.max(0, job.output_refs.length - urls.length);

  return (
    <Card>
      <CardContent className="space-y-3 py-5">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate font-mono text-xs text-muted-foreground">{job.id}</span>
          <Badge variant={completed ? "secondary" : "outline"}>{stateLabel(job.state)}</Badge>
        </div>
        {!terminal && <Progress value={progressPct} aria-label="Render progress" />}
        {failed && job.error && <p className="text-sm text-destructive">{safeServerText(job.error, "This render could not be finished.")}</p>}
        {terminal && job.cost_micros > 0 && (
          <p className="text-xs text-muted-foreground">Charged {formatCost(job.cost_micros)}</p>
        )}

        {job.label && <p className="text-sm">{job.label}</p>}

        {urls.length > 0 && (
          <ul className="space-y-3">
            {urls.map((url) => (
              <li key={url} className="space-y-2">
                <video
                  src={url}
                  controls
                  playsInline
                  preload="metadata"
                  className="w-full max-w-sm rounded-md border border-border bg-black"
                  aria-label="Rendered video"
                />
                <Button asChild size="sm" variant="outline">
                  <a href={url} download target="_blank" rel="noopener noreferrer">
                    <Download className="mr-1 h-4 w-4" aria-hidden /> Download
                  </a>
                </Button>
              </li>
            ))}
          </ul>
        )}
        {completed && hiddenOutputs > 0 && urls.length === 0 && (
          <p className="text-sm text-muted-foreground">
            The render finished, but its output is not available for download yet. Refresh in a
            moment; if it stays unavailable, contact support with the render ID above.
          </p>
        )}

        {!terminal && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={onCheckNow} disabled={busy}>
              <RefreshCw className="mr-1 h-4 w-4" aria-hidden /> Check now
            </Button>
            <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>
              <Ban className="mr-1 h-4 w-4" aria-hidden /> Cancel and refund
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
