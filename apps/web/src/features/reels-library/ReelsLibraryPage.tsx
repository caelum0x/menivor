"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth/clerk-safe";
import {
  AlertTriangle,
  CloudUpload,
  Film,
  LayoutGrid,
  List,
  Loader2,
  Plus,
  RefreshCw,
} from "lucide-react";
import { getMe, listJobsPage } from "@/lib/api";
import type { Job, Me } from "@/lib/types";
import { useTranslations } from "@/lib/i18n/context";
import type { Translator } from "@/lib/i18n/translator";
import { signInHref, signUpHref } from "@/lib/auth-redirect";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { CreditsLink } from "@/components/app-shell/CreditsLink";
import { GuestClaimCard } from "@/src/features/onboarding/GuestClaimCard";
import { getStoredDeviceApiKey } from "@/src/shared/device/session";
import { WinsStrip, tallyFinishedReels } from "@/src/shared/wins";
import { friendlyErrorMessage, isSignedOutError } from "@/src/shared/errors";
import { JobCard } from "@/src/features/jobs-library/components/JobCard";
import { ReelsFilterBar } from "./components/ReelsFilterBar";
import { ReelsTable } from "./components/ReelsTable";
import { ReelsPagination } from "./components/ReelsPagination";
import { ReelActions } from "./components/ReelActions";
import { useReelActions } from "./use-reel-actions";
import {
  countByFilter,
  paginate,
  REEL_PAGE_SIZE,
  selectReels,
  type PageResult,
  type ReelFilter,
} from "./reels-filter";

type LoadState = "loading" | "ready" | "error";
type ViewMode = "grid" | "table";

/** Rows fetched per GET /jobs page (the API maximum). */
const FETCH_PAGE_SIZE = 100;
const GRID_PAGE_SIZE = 12;
const VIEW_KEY = "menivor.library.view";
const LIBRARY_PATH = "/reels";

function errorMessageOf(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

function readViewMode(): ViewMode {
  if (typeof window === "undefined") return "table";
  try {
    return window.localStorage.getItem(VIEW_KEY) === "grid" ? "grid" : "table";
  } catch {
    return "table";
  }
}

/** Merge a fetched page into the list, de-duplicating by job id. */
function mergeJobs(current: readonly Job[], incoming: readonly Job[]): Job[] {
  const seen = new Set(current.map((j) => j.job_id));
  return [...current, ...incoming.filter((j) => !seen.has(j.job_id))];
}

/**
 * The canonical reel LIBRARY (`/reels`; `/dashboard` redirects here). Pages
 * through GET /jobs server-side (load older reels on demand), then filters,
 * searches and displays the loaded rows as a dense table or a card grid.
 * Every row carries rename / archive / cancel / delete controls.
 */
export function ReelsLibraryPage() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const t = useTranslations();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [jobs, setJobs] = React.useState<readonly Job[]>([]);
  const [me, setMe] = React.useState<Me | null>(null);
  const [errorMessage, setErrorMessage] = React.useState<string>("");
  const [signedOut, setSignedOut] = React.useState(false);
  const [hasMore, setHasMore] = React.useState(false);
  const [nextOffset, setNextOffset] = React.useState(0);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [moreError, setMoreError] = React.useState("");
  const [refreshing, setRefreshing] = React.useState(false);

  const [filter, setFilter] = React.useState<ReelFilter>("all");
  const [query, setQuery] = React.useState<string>("");
  const [page, setPage] = React.useState<number>(1);
  const [view, setView] = React.useState<ViewMode>("table");

  React.useEffect(() => {
    setView(readViewMode());
  }, []);

  const changeView = React.useCallback((next: ViewMode) => {
    setView(next);
    setPage(1);
    try {
      window.localStorage.setItem(VIEW_KEY, next);
    } catch {
      // Preference only; the view still switches for this visit.
    }
  }, []);

  const load = React.useCallback(async () => {
    setStatus((prev) => (prev === "ready" ? prev : "loading"));
    setRefreshing(true);
    setErrorMessage("");
    setSignedOut(false);
    setMoreError("");
    // Signed out with no guest session in this browser: every call would 401
    // (console noise, wasted round trips). Show the sign-in prompt directly.
    if (!isSignedIn && !getStoredDeviceApiKey()) {
      setSignedOut(true);
      setStatus("error");
      setRefreshing(false);
      return;
    }
    try {
      const token = (await getToken()) ?? undefined;
      const [meResult, firstPage] = await Promise.all([
        getMe({ token }),
        listJobsPage({ limit: FETCH_PAGE_SIZE, offset: 0, includeArchived: true }, { token }),
      ]);
      setMe(meResult);
      setJobs(firstPage.jobs);
      setHasMore(firstPage.hasMore);
      setNextOffset(firstPage.nextOffset);
      setStatus("ready");
    } catch (err) {
      setSignedOut(isSignedOutError(err));
      setErrorMessage(errorMessageOf(err, t("library.loadError")));
      setStatus("error");
    } finally {
      setRefreshing(false);
    }
  }, [getToken, isSignedIn, t]);

  React.useEffect(() => {
    if (isLoaded) void load();
  }, [isLoaded, load]);

  const loadMore = React.useCallback(async () => {
    setLoadingMore(true);
    setMoreError("");
    try {
      const token = (await getToken()) ?? undefined;
      const next = await listJobsPage(
        { limit: FETCH_PAGE_SIZE, offset: nextOffset, includeArchived: true },
        { token },
      );
      setJobs((prev) => mergeJobs(prev, next.jobs));
      setHasMore(next.hasMore && next.jobs.length > 0);
      setNextOffset(next.nextOffset);
    } catch (err) {
      setMoreError(errorMessageOf(err, "Couldn't load older reels."));
    } finally {
      setLoadingMore(false);
    }
  }, [getToken, nextOffset]);

  const handleUpdated = React.useCallback((updated: Job) => {
    setJobs((prev) => prev.map((j) => (j.job_id === updated.job_id ? updated : j)));
  }, []);
  const handleRemoved = React.useCallback((jobId: string) => {
    setJobs((prev) => prev.filter((j) => j.job_id !== jobId));
    setMe((prev) => (prev ? { ...prev, jobs_count: Math.max(0, prev.jobs_count - 1) } : prev));
  }, []);
  const actions = useReelActions(handleUpdated, handleRemoved);

  const handleFilterChange = React.useCallback((next: ReelFilter) => {
    setFilter(next);
    setPage(1);
  }, []);

  const handleQueryChange = React.useCallback((next: string) => {
    setQuery(next);
    setPage(1);
  }, []);

  const pageSize = view === "grid" ? GRID_PAGE_SIZE : REEL_PAGE_SIZE;
  const counts = React.useMemo(() => countByFilter(jobs), [jobs]);
  const selected = React.useMemo(
    () => selectReels(jobs, filter, query),
    [jobs, filter, query],
  );
  const pageResult = React.useMemo(
    () => paginate(selected, page, pageSize),
    [selected, page, pageSize],
  );

  React.useEffect(() => {
    if (pageResult.page !== page) setPage(pageResult.page);
  }, [pageResult.page, page]);

  const hasAnyReels = jobs.length > 0;
  const tally = React.useMemo(() => tallyFinishedReels(jobs, hasMore), [jobs, hasMore]);
  const isGuest = isLoaded && !isSignedIn && Boolean(me?.email.startsWith("device+"));

  return (
    <main className="min-h-dvh">
      {/* Calendar, scheduled, uploads and film studio live under "More". */}
      <AppTopBar
        extra={<CreditsLink credits={me?.credits} loading={status === "loading"} />}
      />

      {isGuest && <GuestBanner />}

      <section className="container py-8">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{t("library.title")}</h1>
            <p className="text-sm text-muted-foreground">
              {me
                ? t(
                    me.jobs_count === 1 ? "library.subtitleCountOne" : "library.subtitleCount",
                    { count: me.jobs_count, email: me.email },
                  )
                : t("library.subtitleFallback")}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <ViewToggle view={view} onChange={changeView} />
            <Button asChild size="sm">
              <Link href="/create">
                <Plus className="size-4" aria-hidden /> {t("library.newReel")}
              </Link>
            </Button>
          </div>
        </div>

        {isSignedIn && (
          <div className="mb-6">
            <GuestClaimCard onClaimed={() => void load()} />
          </div>
        )}

        {status === "ready" && <WinsStrip tally={tally} />}

        {status === "error" && (
          <ErrorPanel message={errorMessage} signedOut={signedOut} onRetry={() => void load()} t={t} />
        )}

        {status === "loading" && <TableSkeleton />}

        {status === "ready" && !hasAnyReels && <EmptyState t={t} />}

        {status === "ready" && hasAnyReels && (
          <>
            <ReelsFilterBar
              filter={filter}
              query={query}
              counts={counts}
              refreshing={refreshing}
              onFilterChange={handleFilterChange}
              onQueryChange={handleQueryChange}
              onRefresh={() => void load()}
            />

            {pageResult.total === 0 ? (
              <Card>
                <NoMatchState onClear={() => handleFilterChange("all")} t={t} />
              </Card>
            ) : view === "table" ? (
              <Card className="overflow-hidden">
                <ReelsTable reels={pageResult.items} actions={actions} />
                <PaginationRow result={pageResult} setPage={setPage} />
              </Card>
            ) : (
              <>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {pageResult.items.map((job) => (
                    <JobCard
                      key={job.job_id}
                      job={job}
                      actions={<ReelActions job={job} actions={actions} />}
                    />
                  ))}
                </div>
                <Card className="mt-4 overflow-hidden">
                  <PaginationRow result={pageResult} setPage={setPage} />
                </Card>
              </>
            )}

            {hasMore && (
              <div className="mt-6 flex flex-col items-center gap-2">
                <Button
                  variant="outline"
                  onClick={() => void loadMore()}
                  disabled={loadingMore}
                >
                  {loadingMore ? (
                    <Loader2 className="size-4 animate-spin" aria-hidden />
                  ) : (
                    <RefreshCw className="size-4" aria-hidden />
                  )}
                  Load older reels
                </Button>
                <p className="text-xs text-muted-foreground">
                  Showing your {jobs.length} most recent reels.
                </p>
                {moreError && (
                  <p className="text-sm text-destructive" role="alert">
                    {moreError}
                  </p>
                )}
              </div>
            )}
          </>
        )}
      </section>
    </main>
  );
}

function PaginationRow({
  result,
  setPage,
}: Readonly<{
  result: PageResult<Job>;
  setPage: React.Dispatch<React.SetStateAction<number>>;
}>) {
  return (
    <ReelsPagination
      page={result.page}
      pageCount={result.pageCount}
      from={result.from}
      to={result.to}
      total={result.total}
      onPrev={() => setPage((p) => Math.max(1, p - 1))}
      onNext={() => setPage((p) => Math.min(result.pageCount, p + 1))}
    />
  );
}

function ViewToggle({
  view,
  onChange,
}: Readonly<{ view: ViewMode; onChange: (next: ViewMode) => void }>) {
  return (
    <div className="flex rounded-md border border-border" role="group" aria-label="Library view">
      <Button
        type="button"
        variant={view === "table" ? "secondary" : "ghost"}
        size="sm"
        aria-pressed={view === "table"}
        onClick={() => onChange("table")}
      >
        <List className="size-4" aria-hidden />
        <span className="sr-only sm:not-sr-only">Table</span>
      </Button>
      <Button
        type="button"
        variant={view === "grid" ? "secondary" : "ghost"}
        size="sm"
        aria-pressed={view === "grid"}
        onClick={() => onChange("grid")}
      >
        <LayoutGrid className="size-4" aria-hidden />
        <span className="sr-only sm:not-sr-only">Grid</span>
      </Button>
    </div>
  );
}

function GuestBanner() {
  return (
    <div className="border-b border-border bg-primary/5">
      <div className="container flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="flex items-start gap-2 text-sm">
          <CloudUpload className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
          <span>
            <span className="font-medium">You&apos;re using a guest session.</span>{" "}
            <span className="text-muted-foreground">
              Your reels and credits live only in this browser. Create a free
              account to keep them on every device.
            </span>
          </span>
        </p>
        <div className="flex shrink-0 gap-2">
          <Button asChild size="sm">
            <Link href={signUpHref(LIBRARY_PATH)}>Save my work</Link>
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link href={signInHref(LIBRARY_PATH)}>Sign in</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Skeleton className="h-10 w-44" />
        <Skeleton className="h-10 w-64" />
      </div>
      <Card className="overflow-hidden">
        <div className="divide-y divide-border">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3 px-4 py-3">
              <Skeleton className="h-11 w-8 rounded" />
              <Skeleton className="h-4 w-40" />
              <Skeleton className="ml-auto h-5 w-24 rounded-full" />
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function ErrorPanel({
  message,
  signedOut,
  onRetry,
  t,
}: Readonly<{ message: string; signedOut: boolean; onRetry: () => void; t: Translator }>) {
  if (signedOut) return <SignedOutPanel />;
  return (
    <Card className="border-destructive/40 bg-destructive/5">
      <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
          <div>
            <p className="font-medium">{t("library.loadErrorTitle")}</p>
            <p className="text-sm text-muted-foreground">
              {signedOut ? "Sign in to see your reels." : message}
            </p>
          </div>
        </div>
        {signedOut ? (
          <Button asChild size="sm">
            <Link href={signInHref(LIBRARY_PATH)}>Sign in</Link>
          </Button>
        ) : (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw className="size-4" aria-hidden /> {t("common.tryAgain")}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

/** Signed out is not a failure: a calm prompt with one action, no error styling. */
function SignedOutPanel() {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center gap-4 py-16 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-primary/10">
          <Film className="size-6 text-primary" aria-hidden />
        </span>
        <div>
          <p className="font-medium">Your reels live here</p>
          <p className="text-sm text-muted-foreground">Sign in to see your reels.</p>
        </div>
        <Button asChild>
          <Link href={signInHref(LIBRARY_PATH)}>Sign in</Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function EmptyState({ t }: Readonly<{ t: Translator }>) {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center gap-4 py-16 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-primary/10">
          <Film className="size-6 text-primary" aria-hidden />
        </span>
        <div>
          <p className="font-medium">{t("library.emptyTitle")}</p>
          <p className="text-sm text-muted-foreground">{t("library.emptyBody")}</p>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          <Button asChild>
            <Link href="/create">
              <Plus className="size-4" aria-hidden /> {t("library.newReel")}
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/new">Product demo wizard</Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function NoMatchState({
  onClear,
  t,
}: Readonly<{ onClear: () => void; t: Translator }>) {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-center">
      <p className="font-medium">{t("library.noMatchTitle")}</p>
      <p className="text-sm text-muted-foreground">{t("library.noMatchBody")}</p>
      <Button variant="outline" size="sm" onClick={onClear}>
        {t("library.showAll")}
      </Button>
    </div>
  );
}
