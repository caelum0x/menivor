"use client";

import * as React from "react";
import {
  ApiError,
  deleteSavedIdea,
  listSavedIdeas,
  saveIdea,
} from "@/lib/api";
import type { Idea, SavedIdea } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type SavedIdeasStatus = "loading" | "ready" | "error";

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

export interface UseSavedIdeasResult {
  status: SavedIdeasStatus;
  ideas: readonly SavedIdea[];
  errorMessage: string;
  /** Refetch the caller's saved ideas. */
  reload: () => void;
  /** Save an idea; returns the created row (also prepended to the list). */
  save: (idea: Readonly<Idea>) => Promise<SavedIdea>;
  /** Delete a saved idea by id, removing it from the list on success. */
  remove: (id: string) => Promise<void>;
}

/**
 * Owns the caller's saved SPARK ideas: loads them (newest first) and exposes
 * immutable save/delete mutators that keep the local list in sync. Every state
 * transition replaces the list with a fresh array — nothing is mutated.
 */
export function useSavedIdeas(): UseSavedIdeasResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<SavedIdeasStatus>("loading");
  const [ideas, setIdeas] = React.useState<readonly SavedIdea[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");

  const load = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = await getApiToken();
      const result = await listSavedIdeas({ token });
      setIdeas(result);
      setStatus("ready");
    } catch (err) {
      setErrorMessage(errorMessageOf(err, "Couldn't load your saved ideas."));
      setStatus("error");
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const save = React.useCallback(
    async (idea: Readonly<Idea>): Promise<SavedIdea> => {
      const token = await getApiToken();
      const created = await saveIdea(idea, { token });
      setIdeas((prev) => [created, ...prev]);
      return created;
    },
    [getApiToken],
  );

  const remove = React.useCallback(
    async (id: string): Promise<void> => {
      const token = await getApiToken();
      await deleteSavedIdea(id, { token });
      setIdeas((prev) => prev.filter((i) => i.id !== id));
    },
    [getApiToken],
  );

  return {
    status,
    ideas,
    errorMessage,
    reload: () => void load(),
    save,
    remove,
  };
}
