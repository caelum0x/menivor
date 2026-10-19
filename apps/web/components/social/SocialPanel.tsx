"use client";

import * as React from "react";
import {
  AlertTriangle,
  Hash,
  Loader2,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { ApiError, generateSocial } from "@/lib/api";
import type { Job, SocialMeta } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useSocialPlatforms } from "@/components/social/use-social-platforms";
import { SocialPlatformPicker } from "@/components/social/SocialPlatformPicker";
import { SocialResult } from "@/components/social/SocialResult";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface SocialPanelProps {
  job: Job;
}

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * "Caption & Hashtags" panel shown on a finished reel's detail page. Lets the
 * creator pick a target platform and generate an optimized post title + caption +
 * hashtags (POST /jobs/{id}/social), each copyable when posting. The first
 * generation is an explicit click (each call spends LLM tokens); once a result
 * exists, changing the platform regenerates automatically for the new platform.
 */
export function SocialPanel({ job }: Readonly<SocialPanelProps>) {
  const getApiToken = useApiToken();
  const { platforms, status, error, reload } = useSocialPlatforms(true);

  const [platform, setPlatform] = React.useState<string>("");
  const [meta, setMeta] = React.useState<SocialMeta | null>(null);
  const [generatedFor, setGeneratedFor] = React.useState<string>("");
  const [generating, setGenerating] = React.useState(false);
  const [genError, setGenError] = React.useState<string>("");

  // Tracks the in-flight generation so a platform change can cancel the previous
  // request before starting the next (avoids a stale result overwriting a newer).
  const controllerRef = React.useRef<AbortController | undefined>(undefined);

  React.useEffect(
    () => () => controllerRef.current?.abort(),
    [],
  );

  // Default the platform to the first entry once the catalog resolves.
  React.useEffect(() => {
    const first = platforms[0];
    if (!platform && first) {
      setPlatform(first.id);
    }
  }, [platforms, platform]);

  const runGenerate = React.useCallback(
    async (target: string): Promise<void> => {
      if (!target) return;

      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;

      setGenerating(true);
      setGenError("");
      try {
        const token = await getApiToken();
        const result = await generateSocial(
          job.job_id,
          { platform: target },
          { token, signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        setMeta(result);
        setGeneratedFor(target);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setGenError(errorMessageOf(err, "Failed to generate the caption."));
      } finally {
        // Only the most-recent request clears the spinner, so a superseded
        // request never flips it off mid-flight.
        if (controllerRef.current === controller) {
          setGenerating(false);
          controllerRef.current = undefined;
        }
      }
    },
    [getApiToken, job.job_id],
  );

  const handlePlatformChange = React.useCallback(
    (next: string) => {
      setPlatform(next);
      // Regenerate on platform change, but only once the creator has generated
      // at least once (never auto-fire an LLM call on first render).
      if (meta !== null) void runGenerate(next);
    },
    [meta, runGenerate],
  );

  const platformsReady = status === "ready" && platforms.length > 0;
  const canGenerate = platformsReady && !generating && platform.length > 0;
  const hasResult = meta !== null;

  const generatedPlatformName = React.useMemo(() => {
    const match = platforms.find((p) => p.id === generatedFor);
    return match?.name ?? generatedFor;
  }, [platforms, generatedFor]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Hash className="size-5 text-primary" aria-hidden />
          Caption &amp; Hashtags
        </CardTitle>
        <CardDescription>
          Generate an optimized post title, caption, and hashtags tailored to a
          platform. Copy them when you post. Change the platform to regenerate.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {status === "loading" || status === "idle" ? (
          <div className="space-y-2">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-10 w-full rounded-md" />
          </div>
        ) : status === "error" ? (
          <div className="flex flex-col items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3">
            <div className="flex items-start gap-2">
              <AlertTriangle
                className="mt-0.5 size-4 shrink-0 text-destructive"
                aria-hidden
              />
              <p className="text-sm text-muted-foreground">{error}</p>
            </div>
            <Button variant="outline" size="sm" onClick={reload}>
              <RefreshCw className="size-4" aria-hidden /> Try again
            </Button>
          </div>
        ) : platforms.length === 0 ? (
          <p className="rounded-lg border border-border p-3 text-sm text-muted-foreground">
            No social platforms are available right now.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[12rem] flex-1">
                <SocialPlatformPicker
                  platforms={platforms}
                  value={platform}
                  disabled={generating}
                  onChange={handlePlatformChange}
                />
              </div>
              <Button
                onClick={() => void runGenerate(platform)}
                disabled={!canGenerate}
                aria-disabled={!canGenerate}
              >
                {generating ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <Sparkles className="size-4" aria-hidden />
                )}
                {generating
                  ? "Generating…"
                  : hasResult
                    ? "Regenerate"
                    : "Generate captions"}
              </Button>
            </div>

            {genError && <p className="text-sm text-destructive">{genError}</p>}

            {meta && (
              <div className="space-y-2">
                {generatedPlatformName && (
                  <p className="text-xs text-muted-foreground">
                    Tailored for{" "}
                    <span className="font-medium text-foreground">
                      {generatedPlatformName}
                    </span>
                    .
                  </p>
                )}
                <SocialResult meta={meta} />
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
