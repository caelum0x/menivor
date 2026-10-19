"use client";

import { AlertTriangle, Lightbulb, RefreshCw, Sparkles } from "lucide-react";
import type { Idea } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { IdeaCard } from "@/components/ideas/IdeaCard";
import type { GenerateStatus } from "@/components/ideas/use-generate-ideas";

interface IdeaResultsProps {
  status: GenerateStatus;
  ideas: readonly Idea[];
  errorMessage: string;
  /** How many ideas were requested — sizes the loading skeleton grid. */
  requestedCount: number;
  onRetry: () => void;
  onSave: (idea: Readonly<Idea>) => Promise<unknown>;
}

/** Renders the generation lifecycle: idle → loading → ready | error. */
export function IdeaResults({
  status,
  ideas,
  errorMessage,
  requestedCount,
  onRetry,
  onSave,
}: IdeaResultsProps) {
  if (status === "idle") {
    return (
      <Card className="border-dashed">
        <CardContent className="flex flex-col items-center gap-4 py-20 text-center">
          <span className="flex size-12 items-center justify-center rounded-full bg-primary/10">
            <Lightbulb className="size-6 text-primary" aria-hidden />
          </span>
          <div>
            <p className="font-medium">Describe your app to spark ideas</p>
            <p className="max-w-sm text-sm text-muted-foreground">
              SPARK turns your niche into ready-to-shoot viral UGC concepts —
              each one a click away from becoming a reel.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (status === "loading") {
    return <ResultsSkeleton count={requestedCount} />;
  }

  if (status === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <AlertTriangle
              className="mt-0.5 size-5 shrink-0 text-destructive"
              aria-hidden
            />
            <div>
              <p className="font-medium">Couldn&apos;t generate ideas</p>
              <p className="text-sm text-muted-foreground">{errorMessage}</p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw className="size-4" aria-hidden /> Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  // status === "ready"
  if (ideas.length === 0) {
    return (
      <Card className="border-dashed">
        <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
          <Sparkles className="size-6 text-muted-foreground" aria-hidden />
          <p className="max-w-sm text-sm text-muted-foreground">
            No concepts came back this time. Try adding more detail about your
            app or audience, then generate again.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          {ideas.length} {ideas.length === 1 ? "concept" : "concepts"} ready to
          shoot
        </p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="size-4" aria-hidden /> Regenerate
        </Button>
      </div>
      <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {ideas.map((idea, i) => (
          <li key={`${idea.title}-${i}`}>
            <IdeaCard idea={idea} onSave={onSave} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function ResultsSkeleton({ count }: { count: number }) {
  const n = Math.min(Math.max(count, 1), 8);
  return (
    <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: n }).map((_, i) => (
        <li key={i}>
          <Card>
            <CardContent className="space-y-3 p-5">
              <Skeleton className="h-5 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-6 w-40 rounded-full" />
              <Skeleton className="h-8 w-32 rounded-md" />
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  );
}
