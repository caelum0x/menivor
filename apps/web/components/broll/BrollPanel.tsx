"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Clapperboard,
  Loader2,
  RefreshCw,
  Sparkles,
  Wand2,
} from "lucide-react";
import { ApiError, listBrollGenerations, rerunJob } from "@/lib/api";
import {
  BROLL_DEFAULT_AMOUNT,
  BROLL_SOURCES,
  type BrollClip,
  type BrollGeneration,
  type BrollSource,
  type Job,
  JobState,
} from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { BrollClipCard } from "@/components/broll/BrollClipCard";
import { useBrollSuggestions } from "@/components/broll/use-broll-suggestions";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

const SOURCE_LABELS: Record<BrollSource, string> = {
  pexels: "Pexels",
  pixabay: "Pixabay",
};

export interface BrollPanelProps {
  job: Job;
}

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * OPTIONAL "AI B-roll cutaways" panel on the job-detail page. Suggests short,
 * muted stock clips relevant to the reel (POST /jobs/{id}/broll/suggest), lets
 * the creator pick one as an INTRO (before the hook) and one as an OUTRO (after),
 * then re-renders the reel with those clip keys via POST /jobs/{id}/rerun. The
 * main reel keeps its full audio + captions; the B-roll clips are muted.
 */
export function BrollPanel({ job }: Readonly<BrollPanelProps>) {
  const router = useRouter();
  const getApiToken = useApiToken();
  const { clips, status, error, suggest } = useBrollSuggestions(job.job_id);

  const [source, setSource] = React.useState<BrollSource | "">("");
  const [introKey, setIntroKey] = React.useState<string | null>(null);
  const [outroKey, setOutroKey] = React.useState<string | null>(null);
  const [applying, setApplying] = React.useState(false);
  const [applyError, setApplyError] = React.useState<string>("");
  const [studioClips, setStudioClips] = React.useState<readonly BrollGeneration[]>(
    [],
  );

  // Load the caller's finished AI Studio clips so they can be attached directly
  // (no copy-paste). Best-effort: a failure just hides the section.
  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    void (async () => {
      try {
        const token = await getApiToken();
        const rows = await listBrollGenerations({
          token,
          signal: controller.signal,
        });
        if (!cancelled) {
          setStudioClips(
            rows.filter(
              (g) => g.state === JobState.Complete && Boolean(g.broll_key),
            ),
          );
        }
      } catch {
        // Studio clips are optional — degrade to the stock-only panel.
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken]);

  const handleSuggest = React.useCallback(() => {
    suggest({
      source: source || undefined,
      amount: BROLL_DEFAULT_AMOUNT,
    });
  }, [suggest, source]);

  // Toggle a raw R2 key into/out of a role; a key can't be both intro and outro.
  const pickKey = React.useCallback((key: string, role: "intro" | "outro") => {
    if (role === "intro") {
      setIntroKey((prev) => (prev === key ? null : key));
      setOutroKey((prev) => (prev === key ? null : prev));
    } else {
      setOutroKey((prev) => (prev === key ? null : key));
      setIntroKey((prev) => (prev === key ? null : prev));
    }
  }, []);

  const pick = React.useCallback(
    (clip: BrollClip, role: "intro" | "outro") => pickKey(clip.key, role),
    [pickKey],
  );

  const clearSelection = React.useCallback(() => {
    setIntroKey(null);
    setOutroKey(null);
  }, []);

  const hasSelection = introKey !== null || outroKey !== null;

  const handleApply = React.useCallback(async () => {
    if (!hasSelection) return;
    setApplying(true);
    setApplyError("");
    try {
      const token = await getApiToken();
      const created = await rerunJob(
        job.job_id,
        {
          ...(introKey ? { broll_intro_key: introKey } : {}),
          ...(outroKey ? { broll_outro_key: outroKey } : {}),
        },
        { token },
      );
      // Navigate to the new job; this component unmounts on route change.
      router.push(`/jobs/${created.job_id}`);
    } catch (err) {
      setApplyError(errorMessageOf(err, "Failed to re-render with B-roll."));
      setApplying(false);
    }
  }, [getApiToken, hasSelection, introKey, outroKey, job.job_id, router]);

  const loading = status === "loading";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Clapperboard className="size-5 text-primary" aria-hidden />
          AI B-roll cutaways
          <Badge variant="secondary">Optional</Badge>
        </CardTitle>
        <CardDescription>
          Splice a short, muted stock clip as a brief intro (before the hook)
          and/or outro (after) around your reel. Suggestions are auto-matched to
          your topic. Your reel keeps its full audio and captions; applying
          re-renders the reel and costs 1 credit.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="broll-source">Stock source</Label>
            <Select
              id="broll-source"
              value={source}
              disabled={loading || applying}
              onChange={(e) => setSource(e.target.value as BrollSource | "")}
              className="w-40"
            >
              <option value="">Auto</option>
              {BROLL_SOURCES.map((s) => (
                <option key={s} value={s}>
                  {SOURCE_LABELS[s]}
                </option>
              ))}
            </Select>
          </div>

          <Button onClick={handleSuggest} disabled={loading || applying}>
            {loading ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <Sparkles className="size-4" aria-hidden />
            )}
            {loading
              ? "Finding clips…"
              : status === "ready"
                ? "Suggest again"
                : "Suggest clips"}
          </Button>
        </div>

        {status === "error" && (
          <div className="flex flex-col items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3">
            <div className="flex items-start gap-2">
              <AlertTriangle
                className="mt-0.5 size-4 shrink-0 text-destructive"
                aria-hidden
              />
              <p className="text-sm text-muted-foreground">{error}</p>
            </div>
            <Button variant="outline" size="sm" onClick={handleSuggest}>
              <RefreshCw className="size-4" aria-hidden /> Try again
            </Button>
          </div>
        )}

        {loading && <BrollGridSkeleton />}

        {status === "ready" && clips.length === 0 && (
          <p className="rounded-lg border border-border p-3 text-sm text-muted-foreground">
            No stock clips matched this reel. Try a different source.
          </p>
        )}

        {clips.length > 0 && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {clips.map((clip) => (
              <BrollClipCard
                key={clip.key}
                clip={clip}
                isIntro={introKey === clip.key}
                isOutro={outroKey === clip.key}
                disabled={applying}
                onPick={(role) => pick(clip, role)}
              />
            ))}
          </div>
        )}

        {studioClips.length > 0 && (
          <div className="space-y-2 rounded-lg border border-border p-3">
            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-primary" aria-hidden />
              <p className="text-sm font-medium">Your AI Studio clips</p>
              <Badge variant="secondary">AI</Badge>
            </div>
            <ul className="space-y-2">
              {studioClips.map((clip) => {
                const isIntro = introKey === clip.broll_key;
                const isOutro = outroKey === clip.broll_key;
                return (
                  <li
                    key={clip.generation_id}
                    className="flex items-center gap-2"
                  >
                    <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground">
                      {clip.broll_key}
                    </span>
                    <Button
                      type="button"
                      size="sm"
                      variant={isIntro ? "default" : "outline"}
                      disabled={applying}
                      onClick={() => pickKey(clip.broll_key, "intro")}
                    >
                      Intro
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant={isOutro ? "default" : "outline"}
                      disabled={applying}
                      onClick={() => pickKey(clip.broll_key, "outro")}
                    >
                      Outro
                    </Button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {applyError && <p className="text-sm text-destructive">{applyError}</p>}

        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={() => void handleApply()}
            disabled={!hasSelection || applying}
            aria-disabled={!hasSelection || applying}
          >
            {applying ? (
              <RefreshCw className="size-4 animate-spin" aria-hidden />
            ) : (
              <Wand2 className="size-4" aria-hidden />
            )}
            {applying ? "Re-rendering…" : "Re-render with B-roll"}
          </Button>
          <span className="text-xs text-muted-foreground">
            {hasSelection ? (
              <>
                {introKey ? "Intro" : ""}
                {introKey && outroKey ? " + " : ""}
                {outroKey ? "Outro" : ""} selected
                {" · "}
                <button
                  type="button"
                  onClick={clearSelection}
                  disabled={applying}
                  className="underline underline-offset-2 hover:text-foreground disabled:opacity-50"
                >
                  Clear
                </button>
              </>
            ) : (
              "Pick a clip as intro and/or outro to apply."
            )}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

function BrollGridSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <Skeleton key={i} className="aspect-video w-full rounded-lg" />
      ))}
    </div>
  );
}
