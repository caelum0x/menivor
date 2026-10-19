"use client";

import * as React from "react";
import {
  AlertTriangle,
  Award,
  Check,
  Download,
  ImageIcon,
  Loader2,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { ApiError, generateCover } from "@/lib/api";
import type {
  CoverRecommendation,
  GenerateCoverResult,
  Job,
} from "@/lib/types";
import { jobCoverUrl } from "@/lib/job-media";
import { useApiToken } from "@/lib/use-api-token";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useCoverStyles } from "@/components/cover/use-cover-styles";
import { CoverStylePicker } from "@/components/cover/CoverStylePicker";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** Max headline length kept in sync with a sane bold-cover overlay. */
const MAX_HEADLINE = 120;

export interface CoverEditorProps {
  job: Job;
  /** Notifies the parent so it can show the new cover as the reel thumbnail. */
  onGenerated?: (result: GenerateCoverResult) => void;
}

interface CoverPreview {
  url: string;
  style?: string;
}

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Cover / thumbnail editor shown on the job-detail page. Lets the creator type a
 * headline (prefilled from the reel's hook), pick a style, and generate a
 * 1080x1920 cover image (POST /jobs/{id}/cover). The returned cover is previewed
 * with a download link and can be regenerated with a different headline/style.
 */
export function CoverEditor({ job, onGenerated }: Readonly<CoverEditorProps>) {
  const getApiToken = useApiToken();
  const { styles, status, error, reload } = useCoverStyles(true);

  const [headline, setHeadline] = React.useState<string>(job.hook ?? "");
  const [styleId, setStyleId] = React.useState<string>("");
  const [generating, setGenerating] = React.useState(false);
  const [genError, setGenError] = React.useState<string>("");
  const [recommendation, setRecommendation] =
    React.useState<CoverRecommendation | null>(null);
  const [cover, setCover] = React.useState<CoverPreview | null>(() => {
    const url = jobCoverUrl(job);
    return url ? { url } : null;
  });

  // Default the style to the first preset once the catalog resolves.
  React.useEffect(() => {
    const first = styles[0];
    if (!styleId && first) {
      setStyleId(first.id);
    }
  }, [styles, styleId]);

  const handleGenerate = React.useCallback(async () => {
    setGenerating(true);
    setGenError("");
    try {
      const token = await getApiToken();
      const trimmed = headline.trim();
      const result = await generateCover(
        job.job_id,
        {
          headline: trimmed || undefined,
          style: styleId || undefined,
        },
        { token },
      );
      setCover({ url: result.cover_url, style: result.style });
      setRecommendation(result.recommendation ?? null);
      onGenerated?.(result);
    } catch (err) {
      setGenError(errorMessageOf(err, "Failed to generate the cover."));
    } finally {
      setGenerating(false);
    }
  }, [getApiToken, headline, styleId, job.job_id, onGenerated]);

  const stylesReady = status === "ready" && styles.length > 0;
  const canGenerate = stylesReady && !generating;
  const hasCover = cover !== null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <ImageIcon className="size-5 text-primary" aria-hidden />
          Cover
        </CardTitle>
        <CardDescription>
          Generate a custom thumbnail: your reel&apos;s frame with the hook
          overlaid as a bold headline. Change the headline or style and
          regenerate any time.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-5 sm:grid-cols-2">
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="cover-headline">Headline</Label>
              <Input
                id="cover-headline"
                value={headline}
                maxLength={MAX_HEADLINE}
                placeholder="Your bold headline"
                disabled={generating}
                onChange={(e) => setHeadline(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                {headline.trim()
                  ? `${headline.trim().length}/${MAX_HEADLINE} characters`
                  : "Leave empty to use the reel's hook."}
              </p>
            </div>

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
            ) : styles.length === 0 ? (
              <p className="rounded-lg border border-border p-3 text-sm text-muted-foreground">
                No cover styles are available right now.
              </p>
            ) : (
              <CoverStylePicker
                styles={styles}
                value={styleId}
                disabled={generating}
                onChange={setStyleId}
              />
            )}

            <Button
              onClick={() => void handleGenerate()}
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
                : hasCover
                  ? "Regenerate cover"
                  : "Generate cover"}
            </Button>

            {genError && (
              <p className="text-sm text-destructive">{genError}</p>
            )}

            <CoverRecommendationPanel
              recommendation={recommendation}
              disabled={generating}
              activeStyle={styleId}
              onApply={setStyleId}
            />
          </div>

          <CoverPreviewPane cover={cover} generating={generating} />
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * Shows the cover ranker's verdict after a generation: the auto-picked style and
 * the ranked candidates (best first) with their composite score. Each ranked
 * style can be applied to the picker to regenerate with it. Hidden until a
 * recommendation exists; when the ranker degraded (no TYPESAFE_API_KEY) it says
 * so instead of showing meaningless zero scores.
 */
function CoverRecommendationPanel({
  recommendation,
  activeStyle,
  disabled,
  onApply,
}: Readonly<{
  recommendation: CoverRecommendation | null;
  activeStyle: string;
  disabled: boolean;
  onApply: (styleId: string) => void;
}>) {
  if (!recommendation) return null;

  if (recommendation.degraded) {
    return (
      <p className="rounded-lg border border-border bg-secondary/30 p-3 text-xs text-muted-foreground">
        AI cover ranking is off — styles are shown in catalog order. Pick a style
        above, or set a TypeSafe key to auto-rank which cover stops the scroll.
      </p>
    );
  }

  const ranked = recommendation.ranked.filter((entry) => entry.scored);
  if (ranked.length === 0) return null;

  return (
    <div className="space-y-2 rounded-lg border border-border p-3">
      <div className="flex items-center gap-2">
        <Award className="size-4 text-primary" aria-hidden />
        <p className="text-sm font-medium">Ranked by scroll-stopping power</p>
      </div>
      <ul className="space-y-1.5">
        {ranked.map((entry, index) => {
          const isRecommended = entry.id === recommendation.recommended_style;
          const isActive = entry.id === activeStyle;
          return (
            <li key={entry.id} className="flex items-center gap-2 text-sm">
              <span className="w-4 shrink-0 text-right text-xs text-muted-foreground">
                {index + 1}
              </span>
              <span className="flex-1 truncate">
                {entry.name}
                {isRecommended && (
                  <span className="ml-1.5 text-xs font-medium text-primary">
                    Recommended
                  </span>
                )}
              </span>
              <span
                className="shrink-0 tabular-nums text-xs text-muted-foreground"
                title="Composite score (higher stops the scroll better)"
              >
                {entry.composite.toFixed(2)}
              </span>
              {isActive ? (
                <span className="flex w-16 shrink-0 items-center justify-end gap-1 text-xs text-primary">
                  <Check className="size-3.5" aria-hidden /> Selected
                </span>
              ) : (
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onApply(entry.id)}
                  className="w-16 shrink-0 text-right text-xs text-primary underline-offset-2 hover:underline disabled:opacity-50"
                >
                  Use this
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function CoverPreviewPane({
  cover,
  generating,
}: Readonly<{ cover: CoverPreview | null; generating: boolean }>) {
  return (
    <div className="space-y-2">
      <div className="mx-auto w-full max-w-[220px] overflow-hidden rounded-lg border border-border bg-secondary/40">
        {/* 1080x1920 cover renders at 9:16. */}
        <div className="relative aspect-[9/16] w-full">
          {cover ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={cover.url}
              alt="Generated reel cover"
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center p-4 text-center text-xs text-muted-foreground">
              {generating
                ? "Rendering your cover…"
                : "Your generated cover will appear here."}
            </div>
          )}
          {generating && (
            <div className="absolute inset-0 flex items-center justify-center bg-background/60">
              <Loader2 className="size-6 animate-spin text-primary" aria-hidden />
            </div>
          )}
        </div>
      </div>
      {cover && (
        <div className="flex items-center justify-center">
          <Button asChild variant="outline" size="sm">
            <a
              href={cover.url}
              download
              target="_blank"
              rel="noopener noreferrer"
            >
              <Download className="size-4" aria-hidden /> Download
            </a>
          </Button>
        </div>
      )}
    </div>
  );
}
