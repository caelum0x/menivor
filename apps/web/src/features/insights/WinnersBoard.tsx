"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Clock, Layers, Trophy } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  formatCount,
  formatPct,
  MODE_LABELS,
  platformLabel,
  relativeTime,
  statusLabel,
} from "./format";
import type { LoopBoard, LoopCandidate, LoopSummary } from "./types";

const detailHref = (batchId: string) =>
  `/insights/winners/${encodeURIComponent(batchId)}`;

function WinnerCard({ loop }: Readonly<{ loop: LoopSummary }>) {
  return (
    <Link href={detailHref(loop.batch_id)} className="group block">
      <Card className="h-full transition-colors group-hover:border-primary/50">
        <CardContent className="space-y-3 p-5">
          <div className="flex items-start justify-between gap-3">
            <p className="line-clamp-1 text-xs text-muted-foreground">
              {loop.title} · round {loop.generation}
            </p>
            <Badge variant={loop.confidence === "high" ? "success" : "secondary"}>
              {loop.confidence === "high" ? "Clear winner" : "Low confidence"}
            </Badge>
          </div>
          <p className="line-clamp-2 font-semibold leading-snug">
            {loop.winner_hook || "Winning variant"}
          </p>
          <p className="line-clamp-2 text-sm text-muted-foreground">{loop.headline}</p>
          <dl className="grid grid-cols-3 gap-2 text-center text-xs">
            <div className="rounded-md bg-secondary/40 p-2">
              <dt className="text-muted-foreground">Views</dt>
              <dd className="font-semibold">{formatCount(loop.winner_views)}</dd>
            </div>
            <div className="rounded-md bg-secondary/40 p-2">
              <dt className="text-muted-foreground">Avg watch</dt>
              <dd className="font-semibold">{formatPct(loop.winner_avg_watch_frac)}</dd>
            </div>
            <div className="rounded-md bg-secondary/40 p-2">
              <dt className="text-muted-foreground">Engagement</dt>
              <dd className="font-semibold">{formatPct(loop.winner_engagement_rate)}</dd>
            </div>
          </dl>
          <p className="text-xs text-muted-foreground">
            {loop.remake_batch_id
              ? "Remade into 3 new variants"
              : loop.mode === "auto" && loop.conclusive
                ? "Auto remake pending"
                : "Ready to remake"}
          </p>
        </CardContent>
      </Card>
    </Link>
  );
}

function LoopRow({ loop }: Readonly<{ loop: LoopSummary }>) {
  const due = loop.check_due_at ? relativeTime(loop.check_due_at) : "";
  return (
    <li>
      <Link
        href={detailHref(loop.batch_id)}
        className="flex flex-col gap-2 rounded-md px-3 py-3 transition-colors hover:bg-secondary/40 sm:flex-row sm:items-center sm:justify-between"
      >
        <div className="min-w-0">
          <p className="truncate font-medium">{loop.title}</p>
          <p className="text-xs text-muted-foreground">
            Round {loop.generation} · {loop.variant_count} variants ·{" "}
            {loop.platforms.length
              ? loop.platforms.map(platformLabel).join(", ")
              : "You post"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2 text-xs">
          {due && (loop.status === "live" || loop.status === "measuring") && (
            <span className="inline-flex items-center gap-1 text-muted-foreground">
              <Clock className="size-3.5" aria-hidden /> check {due}
            </span>
          )}
          <Badge variant="outline">{MODE_LABELS[loop.mode] ?? loop.mode}</Badge>
          <Badge variant={loop.status === "winner_ready" ? "success" : "secondary"}>
            {statusLabel(loop.status)}
          </Badge>
        </div>
      </Link>
    </li>
  );
}

function CandidateRow({ candidate }: Readonly<{ candidate: LoopCandidate }>) {
  return (
    <li>
      <Link
        href={detailHref(candidate.batch_id)}
        className="flex items-center justify-between gap-3 rounded-md px-3 py-3 transition-colors hover:bg-secondary/40"
      >
        <div className="min-w-0">
          <p className="truncate font-medium">{candidate.title}</p>
          <p className="text-xs text-muted-foreground">
            {candidate.complete_count} of {candidate.variant_count} variants rendered ·{" "}
            {relativeTime(candidate.created_at)}
          </p>
        </div>
        <span className="inline-flex shrink-0 items-center gap-1 text-sm text-primary">
          Set up loop <ArrowRight className="size-4" aria-hidden />
        </span>
      </Link>
    </li>
  );
}

/** Winners board + active loops + projects that can join the loop. */
export function WinnersBoard({ board }: Readonly<{ board: LoopBoard }>) {
  const active = board.loops.filter((l) => !l.winner_job_id);
  return (
    <div className="space-y-8">
      <section aria-labelledby="winners-heading" className="space-y-3">
        <h2 id="winners-heading" className="flex items-center gap-2 text-lg font-semibold">
          <Trophy className="size-5 text-primary" aria-hidden /> Winners
        </h2>
        {board.winners.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No winners yet. A winner is picked once at least two variants have been live long
            enough to compare (48 hours by default).
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {board.winners.map((loop) => (
              <WinnerCard key={loop.batch_id} loop={loop} />
            ))}
          </div>
        )}
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Layers className="size-4" aria-hidden /> Loops in progress
          </CardTitle>
        </CardHeader>
        <CardContent>
          {active.length === 0 ? (
            <p className="text-sm text-muted-foreground">No loops running.</p>
          ) : (
            <ul className="-mx-3 divide-y divide-border">
              {active.map((loop) => (
                <LoopRow key={loop.batch_id} loop={loop} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Start a loop</CardTitle>
          <p className="text-sm text-muted-foreground">
            Projects from the last 60 days with at least two variants. Remaking a winner renders{" "}
            3 new variants for {board.remake_cost_credits} credits.
          </p>
        </CardHeader>
        <CardContent>
          {board.candidates.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Create a reel with 2 or 3 variants to compare hooks, then come back here.
            </p>
          ) : (
            <ul className="-mx-3 divide-y divide-border">
              {board.candidates.map((c) => (
                <CandidateRow key={c.batch_id} candidate={c} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
