"use client";

import * as React from "react";
import type { GenerateIdeasRequest } from "@/lib/types";
import { IdeaForm } from "@/components/ideas/IdeaForm";
import { IdeaResults } from "@/components/ideas/IdeaResults";
import { SavedIdeasList } from "@/components/ideas/SavedIdeasList";
import { useGenerateIdeas } from "@/components/ideas/use-generate-ideas";
import { useSavedIdeas } from "@/components/ideas/use-saved-ideas";

/**
 * The SPARK page body: a brief form + generated concepts on the left, the
 * caller's saved ideas on the right. Owns both data hooks so a save from a
 * generated card immediately shows up in the saved list.
 */
export function IdeasView() {
  const generator = useGenerateIdeas();
  const saved = useSavedIdeas();

  const handleGenerate = React.useCallback(
    (req: GenerateIdeasRequest) => {
      void generator.generate(req);
    },
    [generator],
  );

  const handleRetry = React.useCallback(() => {
    if (generator.lastRequest) void generator.generate(generator.lastRequest);
  }, [generator]);

  const requestedCount = generator.lastRequest?.count ?? 5;

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-8">
        <IdeaForm
          onGenerate={handleGenerate}
          loading={generator.status === "loading"}
        />
        <IdeaResults
          status={generator.status}
          ideas={generator.ideas}
          errorMessage={generator.errorMessage}
          requestedCount={requestedCount}
          onRetry={handleRetry}
          onSave={saved.save}
        />
      </div>

      <aside className="lg:sticky lg:top-6 lg:self-start">
        <SavedIdeasList
          status={saved.status}
          ideas={saved.ideas}
          errorMessage={saved.errorMessage}
          onReload={saved.reload}
          onDelete={saved.remove}
        />
      </aside>
    </div>
  );
}
