"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  Bookmark,
  BookmarkCheck,
  Loader2,
  Wand2,
} from "lucide-react";
import type { Idea } from "@/lib/types";
import { ApiError } from "@/lib/api";
import { stashSparkPrefill } from "@/lib/spark-prefill";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { IdeaChips } from "@/components/ideas/IdeaChips";
import { ideaToPrefill } from "@/components/ideas/idea-mapping";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface IdeaCardProps {
  idea: Readonly<Idea>;
  /** Persists the idea; resolves when saved. */
  onSave: (idea: Readonly<Idea>) => Promise<unknown>;
}

type SaveState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved" }
  | { status: "error"; message: string };

/**
 * A single generated concept. "Make this" stashes the idea's create-job fields
 * and routes to the wizard (pre-filled); "Save" persists it for later. Both
 * actions have their own loading + error states.
 */
export function IdeaCard({ idea, onSave }: IdeaCardProps) {
  const router = useRouter();
  const [save, setSave] = React.useState<SaveState>({ status: "idle" });

  const handleMakeThis = React.useCallback(() => {
    stashSparkPrefill(ideaToPrefill(idea));
    router.push("/new");
  }, [idea, router]);

  const handleSave = React.useCallback(async () => {
    setSave({ status: "saving" });
    try {
      await onSave(idea);
      setSave({ status: "saved" });
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Couldn't save this idea. Please try again.");
      setSave({ status: "error", message });
    }
  }, [idea, onSave]);

  const saved = save.status === "saved";

  return (
    <Card className="flex h-full flex-col">
      <CardContent className="flex flex-1 flex-col gap-4 p-5">
        <div className="space-y-1.5">
          <h3 className="text-base font-semibold leading-snug">{idea.title}</h3>
          <p className="text-sm font-medium text-primary">
            &ldquo;{idea.hook}&rdquo;
          </p>
        </div>

        {idea.angle && (
          <p className="text-sm text-muted-foreground">{idea.angle}</p>
        )}

        {idea.script_outline.length > 0 && (
          <ol className="space-y-1 text-sm text-muted-foreground">
            {idea.script_outline.map((beat, i) => (
              <li key={i} className="flex gap-2">
                <span className="font-medium text-foreground/70">{i + 1}.</span>
                <span>{beat}</span>
              </li>
            ))}
          </ol>
        )}

        <div className="mt-auto space-y-3 pt-2">
          <IdeaChips idea={idea} />

          {save.status === "error" && (
            <p
              role="alert"
              className="flex items-center gap-1.5 text-xs text-destructive"
            >
              <AlertCircle className="size-3.5 shrink-0" aria-hidden />
              {save.message}
            </p>
          )}

          <div className="flex items-center gap-2">
            <Button type="button" size="sm" onClick={handleMakeThis}>
              <Wand2 aria-hidden /> Make this
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={handleSave}
              disabled={save.status === "saving" || saved}
            >
              {save.status === "saving" ? (
                <>
                  <Loader2 className="animate-spin" aria-hidden /> Saving…
                </>
              ) : saved ? (
                <>
                  <BookmarkCheck aria-hidden /> Saved
                </>
              ) : (
                <>
                  <Bookmark aria-hidden /> Save
                </>
              )}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
