"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth/clerk-safe";
import {
  AlertTriangle,
  Clapperboard,
  Film,
  LayoutGrid,
  RefreshCw,
  Clock,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslations } from "@/lib/i18n/context";
import { ApiError } from "@/src/shared/api";

import {
  listShowcaseTemplates,
  listCompletedReels,
  type TemplateSummary,
  type ShowcaseReel,
} from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

interface ShowcaseData {
  templates: TemplateSummary[];
  reels: ShowcaseReel[];
}

function formatDuration(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

function TemplateCard({ tmpl }: Readonly<{ tmpl: TemplateSummary }>) {
  const t = useTranslations();
  return (
    <Card className="flex flex-col">
      <CardContent className="flex flex-grow flex-col gap-3 p-5">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="font-semibold leading-tight">{tmpl.name}</p>
            <p className="mt-0.5 text-xs capitalize text-muted-foreground">
              {tmpl.genre.replace(/_/g, " ")}
            </p>
          </div>
          <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
            {tmpl.layout}
          </span>
        </div>

        {tmpl.description && (
          <p className="line-clamp-2 text-xs text-muted-foreground">
            {tmpl.description}
          </p>
        )}

        <div className="mt-auto flex flex-wrap gap-2 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" aria-hidden />
            {formatDuration(tmpl.default_duration_s)}
          </span>
          <span className="flex items-center gap-1">
            <LayoutGrid className="h-3 w-3" aria-hidden />
            {tmpl.slot_count} {t("showcase.slots")}
          </span>
        </div>

        {tmpl.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {tmpl.tags.slice(0, 4).map((tag) => (
              <span
                key={tag}
                className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        <Button asChild variant="outline" size="sm" className="w-full">
          <Link href={`/catalog?template=${encodeURIComponent(tmpl.slug)}`}>
            {t("showcase.useTemplate")}
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function ReelCard({ reel }: Readonly<{ reel: ShowcaseReel }>) {
  const t = useTranslations();
  return (
    <Card className="flex flex-col overflow-hidden">
      {reel.poster_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={reel.poster_url}
          alt={reel.hook ?? "Reel poster"}
          className="aspect-video w-full object-cover"
        />
      ) : (
        <div className="flex aspect-video w-full items-center justify-center bg-muted">
          <Film className="h-8 w-8 text-muted-foreground/40" aria-hidden />
        </div>
      )}
      <CardContent className="flex flex-grow flex-col gap-2 p-4">
        {reel.hook && (
          <p className="line-clamp-2 text-sm font-medium">{reel.hook}</p>
        )}
        {reel.created_at && (
          <p className="text-xs text-muted-foreground">
            {new Date(reel.created_at).toLocaleDateString()}
          </p>
        )}
        {reel.result_url && (
          <Button asChild variant="outline" size="sm" className="mt-auto w-full">
            <a href={reel.result_url} target="_blank" rel="noopener noreferrer">
              {t("showcase.previewReel")}
            </a>
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function ShowcaseSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-6 w-48" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="space-y-3 p-5">
              <Skeleton className="h-5 w-36" />
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-8 w-full rounded" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function ErrorBanner({
  message,
  onRetry,
}: Readonly<{ message: string; onRetry: () => void }>) {
  const t = useTranslations();
  return (
    <Card className="border-destructive/40 bg-destructive/5">
      <CardContent className="flex items-start gap-3 p-5 sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <AlertTriangle
            className="mt-0.5 h-5 w-5 shrink-0 text-destructive"
            aria-hidden
          />
          <p className="text-sm">{message}</p>
        </div>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="mr-1 h-4 w-4" aria-hidden />
          {t("common.tryAgain")}
        </Button>
      </CardContent>
    </Card>
  );
}

/**
 * Showcase hub — templates catalog + the caller's completed reels.
 *
 * Templates come from GET /templates (no auth required, always visible).
 * The caller's completed reels come from GET /jobs (requires auth).
 *
 * There is no dedicated public "published reels" endpoint, so the gallery
 * shows templates as the canonical public surface and labels both sources
 * clearly in the UI.
 */
export function ShowcasePage() {
  const t = useTranslations();
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [data, setData] = React.useState<ShowcaseData>({
    templates: [],
    reels: [],
  });
  const [errorMessage, setErrorMessage] = React.useState("");

  const load = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = (await getToken()) ?? undefined;
      const [tmplRes, reels] = await Promise.all([
        listShowcaseTemplates(),
        isSignedIn
          ? listCompletedReels(20, { token })
          : Promise.resolve([]),
      ]);
      setData({ templates: tmplRes.templates, reels });
      setStatus("ready");
    } catch (err) {
      const msg =
        friendlyErrorMessage(err, "Could not load showcase.");
      setErrorMessage(msg);
      setStatus("error");
    }
  }, [getToken, isSignedIn]);

  React.useEffect(() => {
    if (isLoaded) void load();
  }, [isLoaded, load]);

  return (
    <main className="mx-auto max-w-6xl space-y-10 px-4 py-8">
      {/* Header */}
      <header className="space-y-1">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Clapperboard className="h-6 w-6 text-primary" aria-hidden />
            <h1 className="text-2xl font-semibold">{t("showcase.title")}</h1>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load()}
            disabled={status === "loading"}
          >
            <RefreshCw
              className={
                status === "loading"
                  ? "mr-2 h-4 w-4 animate-spin"
                  : "mr-2 h-4 w-4"
              }
              aria-hidden
            />
            {t("discover.refresh")}
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">{t("showcase.subtitle")}</p>
      </header>

      {status === "error" && (
        <ErrorBanner message={errorMessage} onRetry={() => void load()} />
      )}

      {status === "loading" && <ShowcaseSkeleton />}

      {status === "ready" && (
        <>
          {/* Templates section */}
          <section className="space-y-4">
            <div>
              <h2 className="text-lg font-semibold">
                {t("showcase.templatesHeading")}
              </h2>
              <p className="mt-0.5 text-sm text-muted-foreground">
                {t("showcase.templatesDesc")}
              </p>
            </div>

            {data.templates.length === 0 ? (
              <Card>
                <CardContent className="py-8 text-center text-sm text-muted-foreground">
                  {t("showcase.noTemplates")}
                </CardContent>
              </Card>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {data.templates.map((tmpl) => (
                  <TemplateCard key={tmpl.slug} tmpl={tmpl} />
                ))}
              </div>
            )}
          </section>

          {/* Completed reels section */}
          <section className="space-y-4">
            <div>
              <h2 className="text-lg font-semibold">
                {t("showcase.myReelsHeading")}
              </h2>
              <p className="mt-0.5 text-sm text-muted-foreground">
                {t("showcase.myReelsDesc")}
              </p>
            </div>

            {!isSignedIn ? (
              <Card>
                <CardContent className="py-8 text-center text-sm text-muted-foreground">
                  {t("showcase.signInPrompt")}{" "}
                  <Link href="/sign-in" className="text-primary underline-offset-2 hover:underline">
                    {t("common.signIn")}
                  </Link>
                </CardContent>
              </Card>
            ) : data.reels.length === 0 ? (
              <Card>
                <CardContent className="py-8 text-center text-sm text-muted-foreground">
                  {t("showcase.noReels")}{" "}
                  <Link href="/reels" className="text-primary underline-offset-2 hover:underline">
                    {t("library.newReel")}
                  </Link>
                </CardContent>
              </Card>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {data.reels.map((reel) => (
                  <ReelCard key={reel.job_id} reel={reel} />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}
