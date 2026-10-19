"use client";

import * as React from "react";
import {
  AlertTriangle,
  Crown,
  Loader2,
  Sparkles,
  Target,
  Trophy,
  Wand2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { RankHooksError, splitHookLines } from "@/lib/growth/rank-hooks-client";
import { rankHooksAuthenticated } from "@/lib/hook-finder-client";
import {
  MAX_HOOK_VARIANTS,
  type PolicyRisk,
  type RankedHook,
  type RankHooksResponse,
} from "@/lib/growth/types";

type Status = "idle" | "loading" | "ready" | "error";

const EXAMPLE = [
  "POV: you just found the editing app that does the boring work for you",
  "I tried 7 faceless video tools so you don't have to — here's the only one worth it",
  "This AI turns a screen recording into a viral reel in 60 seconds",
  "Stop posting Reels until you watch this",
].join("\n");

const POLICY_BADGE: Record<PolicyRisk, { variant: BadgeVariant; label: string }> = {
  low: { variant: "success", label: "Policy: clear" },
  medium: { variant: "outline", label: "Policy: review" },
  high: { variant: "destructive", label: "Policy: risk" },
};

/** 0..1 → whole-percent string. */
function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/** Winning Hook Finder — paste hook variants, rank them with Jev, crown a winner. */
export function HookFinder() {
  const [text, setText] = React.useState("");
  const [status, setStatus] = React.useState<Status>("idle");
  const [result, setResult] = React.useState<RankHooksResponse | null>(null);
  const [errorMessage, setErrorMessage] = React.useState("");

  const lines = React.useMemo(() => splitHookLines(text), [text]);
  const tooMany = lines.length > MAX_HOOK_VARIANTS;
  const canSubmit = lines.length >= 2 && !tooMany && status !== "loading";

  const onSubmit = React.useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      if (lines.length < 2 || tooMany) return;
      setStatus("loading");
      setErrorMessage("");
      try {
        const response = await rankHooksAuthenticated(lines.slice(0, MAX_HOOK_VARIANTS));
        setResult(response);
        setStatus("ready");
      } catch (error) {
        setErrorMessage(
          error instanceof RankHooksError
            ? error.message
            : "Something went wrong ranking your hooks. Please try again.",
        );
        setStatus("error");
      }
    },
    [lines, tooMany],
  );

  return (
    <div className="grid gap-6">
      <form onSubmit={onSubmit} className="grid gap-3">
        <label htmlFor="hook-variants" className="text-sm font-medium">
          Your hook variants{" "}
          <span className="text-muted-foreground">(one per line, 2–{MAX_HOOK_VARIANTS})</span>
        </label>
        <Textarea
          id="hook-variants"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={6}
          placeholder={"Paste one hook per line, e.g.\n" + EXAMPLE}
          aria-describedby="hook-variants-help"
        />
        <div
          id="hook-variants-help"
          className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground"
        >
          <span>
            {lines.length} hook{lines.length === 1 ? "" : "s"} entered
            {tooMany && (
              <span className="ml-1 text-destructive">
                — keep it to {MAX_HOOK_VARIANTS} or fewer
              </span>
            )}
          </span>
          <button
            type="button"
            className="underline underline-offset-2 hover:text-foreground"
            onClick={() => setText(EXAMPLE)}
          >
            Use example hooks
          </button>
        </div>
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={!canSubmit}>
            {status === "loading" ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                Ranking with Jev…
              </>
            ) : (
              <>
                <Wand2 className="mr-2 h-4 w-4" aria-hidden />
                Find the winning hook
              </>
            )}
          </Button>
          {lines.length < 2 && (
            <span className="text-xs text-muted-foreground">
              Add at least 2 variants to compare.
            </span>
          )}
        </div>
      </form>

      {status === "error" && (
        <Card className="border-destructive/40">
          <CardContent className="flex items-start gap-3 py-4 text-sm">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />
            <p>{errorMessage}</p>
          </CardContent>
        </Card>
      )}

      {status === "ready" && result && <Results result={result} />}
    </div>
  );
}

function Results({ result }: { result: RankHooksResponse }) {
  const { winner, variants, recommendedAngle, degraded, note } = result;
  return (
    <section className="grid gap-4" aria-live="polite">
      {degraded && (
        <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <p>
            <strong>Heuristic ranking only.</strong>{" "}
            {note ?? "The Jev model did not run for this request."}
          </p>
        </div>
      )}

      {winner && (
        <Card className="border-primary/50 bg-primary/[0.04]">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <Crown className="h-5 w-5 text-primary" aria-hidden />
              Winning hook
              {!degraded && (
                <Badge variant="default" className="ml-auto">
                  <Sparkles className="h-3 w-3" aria-hidden /> Jev
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3">
            <p className="text-lg font-medium leading-snug">{winner.text}</p>
            <SignalBadges hook={winner} />
            {recommendedAngle && (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Target className="h-4 w-4" aria-hidden />
                Recommended angle:{" "}
                <span className="font-medium text-foreground">{recommendedAngle.label}</span>
              </p>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-2">
        <h2 className="text-sm font-semibold text-muted-foreground">
          Full ranking ({variants.length})
        </h2>
        <ol className="grid gap-2">
          {variants.map((hook) => (
            <li key={hook.id}>
              <VariantRow hook={hook} />
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function VariantRow({ hook }: { hook: RankedHook }) {
  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-lg border p-3",
        hook.isWinner ? "border-primary/50 bg-primary/[0.04]" : "border-border",
      )}
    >
      <div
        className={cn(
          "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-semibold",
          hook.isWinner ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
        )}
        aria-label={`Rank ${hook.rank}`}
      >
        {hook.isWinner ? <Trophy className="h-3.5 w-3.5" aria-hidden /> : hook.rank}
      </div>
      <div className="grid flex-1 gap-2">
        <p className="text-sm leading-snug">{hook.text}</p>
        <SignalBadges hook={hook} />
      </div>
    </div>
  );
}

function SignalBadges({ hook }: { hook: RankedHook }) {
  const policy = POLICY_BADGE[hook.policyRisk];
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant="secondary" title="Composite hook score">
        Score {pct(hook.composite)}
      </Badge>
      <Badge variant={hook.strength >= 0.66 ? "success" : "outline"} title="Scroll-stopping strength">
        Strength {pct(hook.strength)}
      </Badge>
      <Badge variant={hook.slop >= 0.5 ? "destructive" : "outline"} title="AI-slop / engagement-bait feel (lower is better)">
        Slop {pct(hook.slop)}
      </Badge>
      <Badge variant={policy.variant} title="Platform / ad policy risk">
        {policy.label}
      </Badge>
      <Badge variant="outline" title="Attention angle">
        {hook.angleLabel}
      </Badge>
    </div>
  );
}
