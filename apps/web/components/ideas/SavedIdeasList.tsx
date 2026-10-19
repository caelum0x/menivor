"use client";

import * as React from "react";
import {
  AlertTriangle,
  Bookmark,
  Loader2,
  RefreshCw,
  Trash2,
  Wand2,
} from "lucide-react";
import { useRouter } from "next/navigation";
import type { SavedIdea } from "@/lib/types";
import { ApiError } from "@/lib/api";
import { stashSparkPrefill } from "@/lib/spark-prefill";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { IdeaChips } from "@/components/ideas/IdeaChips";
import { ideaToPrefill } from "@/components/ideas/idea-mapping";
import type { SavedIdeasStatus } from "@/components/ideas/use-saved-ideas";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface SavedIdeasListProps {
  status: SavedIdeasStatus;
  ideas: readonly SavedIdea[];
  errorMessage: string;
  onReload: () => void;
  onDelete: (id: string) => Promise<void>;
}

/** The caller's saved ideas, each with "Make this" and a delete control. */
export function SavedIdeasList({
  status,
  ideas,
  errorMessage,
  onReload,
  onDelete,
}: SavedIdeasListProps) {
  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-4">
        <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
          <Bookmark className="size-4 text-primary" aria-hidden />
          Saved ideas
          {status === "ready" && ideas.length > 0 && (
            <span className="text-sm font-normal text-muted-foreground">
              {ideas.length}
            </span>
          )}
        </h2>
        <Button
          variant="outline"
          size="sm"
          onClick={onReload}
          disabled={status === "loading"}
        >
          <RefreshCw
            className={status === "loading" ? "size-4 animate-spin" : "size-4"}
            aria-hidden
          />
          Refresh
        </Button>
      </div>

      {status === "loading" && <SavedSkeleton />}

      {status === "error" && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex flex-col items-start gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <AlertTriangle
                className="mt-0.5 size-5 shrink-0 text-destructive"
                aria-hidden
              />
              <div>
                <p className="font-medium">Couldn&apos;t load saved ideas</p>
                <p className="text-sm text-muted-foreground">{errorMessage}</p>
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={onReload}>
              <RefreshCw className="size-4" aria-hidden /> Try again
            </Button>
          </CardContent>
        </Card>
      )}

      {status === "ready" && ideas.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <span className="flex size-11 items-center justify-center rounded-full bg-primary/10">
              <Bookmark className="size-5 text-primary" aria-hidden />
            </span>
            <p className="max-w-sm text-sm text-muted-foreground">
              No saved ideas yet. Generate concepts above and tap{" "}
              <span className="font-medium text-foreground">Save</span> to keep
              your favourites here.
            </p>
          </CardContent>
        </Card>
      )}

      {status === "ready" && ideas.length > 0 && (
        <ul className="space-y-3">
          {ideas.map((idea) => (
            <li key={idea.id}>
              <SavedIdeaRow idea={idea} onDelete={onDelete} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SavedIdeaRow({
  idea,
  onDelete,
}: {
  idea: Readonly<SavedIdea>;
  onDelete: (id: string) => Promise<void>;
}) {
  const router = useRouter();
  const [deleting, setDeleting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const handleMakeThis = React.useCallback(() => {
    stashSparkPrefill(ideaToPrefill(idea));
    router.push("/new");
  }, [idea, router]);

  const handleDelete = React.useCallback(async () => {
    setDeleting(true);
    setError(null);
    try {
      await onDelete(idea.id);
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Couldn't delete this idea. Please try again.");
      setError(message);
      setDeleting(false);
    }
  }, [idea.id, onDelete]);

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <h3 className="truncate text-sm font-semibold">{idea.title}</h3>
            <p className="text-sm text-primary">&ldquo;{idea.hook}&rdquo;</p>
          </div>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            onClick={handleDelete}
            disabled={deleting}
            aria-label={`Delete idea: ${idea.title}`}
            className="size-8 shrink-0 text-muted-foreground hover:text-destructive"
          >
            {deleting ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <Trash2 className="size-4" aria-hidden />
            )}
          </Button>
        </div>

        <IdeaChips idea={idea} />

        {error && (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        )}

        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={handleMakeThis}
        >
          <Wand2 aria-hidden /> Make this
        </Button>
      </CardContent>
    </Card>
  );
}

function SavedSkeleton() {
  return (
    <ul className="space-y-3">
      {Array.from({ length: 3 }).map((_, i) => (
        <li key={i}>
          <Card>
            <CardContent className="space-y-3 p-4">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-6 w-40 rounded-full" />
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  );
}
