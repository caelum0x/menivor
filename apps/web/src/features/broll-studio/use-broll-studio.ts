"use client";

import * as React from "react";
import {
  ApiError,
  POLL_INTERVAL_MS,
  generateBroll,
  getBrollGeneration,
  listBrollGenerations,
} from "@/lib/api";
import type { BrollGenerateRequest, BrollGeneration } from "@/lib/types";
import { isTerminalState } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type BrollStudioStatus = "idle" | "submitting" | "error";

export interface UseBrollStudioResult {
  /** Durable account history plus generations started this session, newest first. */
  generations: readonly BrollGeneration[];
  /** Submission state of the prompt form (polling runs independently). */
  status: BrollStudioStatus;
  errorMessage: string;
  /** Start one generation and begin polling it. Resolves to the initial snapshot. */
  generate: (body: BrollGenerateRequest) => Promise<BrollGeneration>;
  /** Forget a generation from the local list (does not cancel server-side work). */
  dismiss: (generationId: string) => void;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err, fallback);
  if (err instanceof Error) return friendlyErrorMessage(err, fallback);
  return fallback;
}

/**
 * Owns the authenticated account's AI B-roll generations: loads durable
 * history, submits
 * `POST /generation/broll/generate` and
 * polls each non-terminal generation at {@link POLL_INTERVAL_MS} until it
 * completes or fails, replacing its snapshot with the server's authoritative
 * value each tick. Polling is driven by an effect over the current generations;
 * a page refresh rehydrates from the API rather than treating browser memory as
 * authoritative history.
 */
export function useBrollStudio(): UseBrollStudioResult {
  const getApiToken = useApiToken();
  const [generations, setGenerations] = React.useState<readonly BrollGeneration[]>(
    [],
  );
  const [status, setStatus] = React.useState<BrollStudioStatus>("idle");
  const [errorMessage, setErrorMessage] = React.useState("");
  const pendingCreate = React.useRef<{ signature: string; key: string } | null>(null);

  React.useEffect(() => {
    let active = true;
    const controller = new AbortController();
    void (async () => {
      try {
        const token = await getApiToken();
        const history = await listBrollGenerations({
          token,
          signal: controller.signal,
        });
        if (active) {
          setGenerations((current) => {
            const historyIds = new Set(history.map((item) => item.generation_id));
            return [
              ...current.filter((item) => !historyIds.has(item.generation_id)),
              ...history,
            ];
          });
        }
      } catch (err) {
        if (!active || controller.signal.aborted) return;
        setStatus("error");
        setErrorMessage(messageFor(err, "Failed to load B-roll history."));
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
  }, [getApiToken]);

  // Immutable upsert: replace the matching snapshot, or prepend a new one.
  const upsert = React.useCallback((next: BrollGeneration) => {
    setGenerations((prev) => {
      const idx = prev.findIndex(
        (g) => g.generation_id === next.generation_id,
      );
      if (idx === -1) return [next, ...prev];
      const copy = prev.slice();
      copy[idx] = next;
      return copy;
    });
  }, []);

  const generate = React.useCallback(
    async (body: BrollGenerateRequest): Promise<BrollGeneration> => {
      const signature = JSON.stringify(body);
      if (!pendingCreate.current || pendingCreate.current.signature !== signature) {
        pendingCreate.current = {
          signature,
          key: `broll-${crypto.randomUUID()}`,
        };
      }
      setStatus("submitting");
      setErrorMessage("");
      try {
        const token = await getApiToken();
        const snapshot = await generateBroll(body, {
          token,
          idempotencyKey: pendingCreate.current.key,
        });
        upsert(snapshot);
        pendingCreate.current = null;
        setStatus("idle");
        return snapshot;
      } catch (err) {
        setStatus("error");
        setErrorMessage(messageFor(err, "Failed to start generation."));
        throw err;
      }
    },
    [getApiToken, upsert],
  );

  const dismiss = React.useCallback((generationId: string) => {
    setGenerations((prev) =>
      prev.filter((g) => g.generation_id !== generationId),
    );
  }, []);

  // Poll every non-terminal generation on a shared interval. The effect re-runs
  // whenever the set of pending ids changes (a new submit, or one going
  // terminal), so completed generations stop being polled.
  const pendingIds = generations
    .filter((g) => !isTerminalState(g.state))
    .map((g) => g.generation_id)
    .join(",");

  React.useEffect(() => {
    if (!pendingIds) return;
    const ids = pendingIds.split(",");
    const controller = new AbortController();
    let cancelled = false;

    const timer = setInterval(() => {
      void (async () => {
        let token: string | undefined;
        try {
          token = await getApiToken();
        } catch {
          return; // transient token failure: try again next tick
        }
        for (const id of ids) {
          try {
            const snapshot = await getBrollGeneration(id, {
              token,
              signal: controller.signal,
            });
            if (!cancelled) upsert(snapshot);
          } catch (err) {
            if (err instanceof DOMException && err.name === "AbortError") return;
            // Best-effort poll: a transient error is retried next tick.
          }
        }
      })();
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      controller.abort();
      clearInterval(timer);
    };
  }, [pendingIds, getApiToken, upsert]);

  return { generations, status, errorMessage, generate, dismiss };
}
