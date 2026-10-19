"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth, UserButton } from "@/components/auth/clerk-safe";
import {
  AlertTriangle,
  RefreshCw,
  Store,
  Upload,
} from "lucide-react";
import {
  ApiError,
  browseMarketplace,
  cloneTemplate,
  getMarketplaceLineage,
  publishTemplate,
  rateTemplate,
} from "@/lib/api";
import type {
  MarketplaceSort,
  MarketplaceTemplate,
  PublishTemplateRequest,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { MarketplaceFilters } from "@/components/marketplace/MarketplaceFilters";
import { PublishDialog } from "@/components/marketplace/PublishDialog";
import { TemplateCard } from "@/components/marketplace/TemplateCard";
import { MenivorMark } from "@/components/brand/MenivorMark";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

/** How many listings to request per browse (clamped to 100 server-side). */
const PAGE_SIZE = 48;
/** Debounce applied to the free-text filters before refetching. */
const FILTER_DEBOUNCE_MS = 300;

/** Debounce a rapidly-changing value (search box) before it drives a fetch. */
function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

export default function MarketplacePage() {
  const { getToken, isLoaded } = useAuth();

  const [query, setQuery] = React.useState("");
  const [tag, setTag] = React.useState("");
  const [language, setLanguage] = React.useState("");
  const [sort, setSort] = React.useState<MarketplaceSort>("top");

  const [status, setStatus] = React.useState<LoadState>("loading");
  const [templates, setTemplates] = React.useState<readonly MarketplaceTemplate[]>(
    [],
  );
  const [errorMessage, setErrorMessage] = React.useState<string>("");
  const [publishOpen, setPublishOpen] = React.useState(false);

  const debouncedQuery = useDebounced(query, FILTER_DEBOUNCE_MS);
  const debouncedTag = useDebounced(tag, FILTER_DEBOUNCE_MS);

  const load = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = (await getToken()) ?? undefined;
      const result = await browseMarketplace(
        {
          query: debouncedQuery,
          tag: debouncedTag,
          language,
          sort,
          limit: PAGE_SIZE,
        },
        { token },
      );
      setTemplates(result);
      setStatus("ready");
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Something went wrong loading the marketplace.");
      setErrorMessage(message);
      setStatus("error");
    }
  }, [getToken, debouncedQuery, debouncedTag, language, sort]);

  React.useEffect(() => {
    if (isLoaded) void load();
  }, [isLoaded, load]);

  const handleClone = React.useCallback(
    async (id: string) => {
      const token = (await getToken()) ?? undefined;
      return cloneTemplate(id, { token });
    },
    [getToken],
  );

  const handleRate = React.useCallback(
    async (id: string, stars: number) => {
      const token = (await getToken()) ?? undefined;
      return rateTemplate(id, stars, { token });
    },
    [getToken],
  );

  const handleLineage = React.useCallback(
    async (id: string) => {
      const token = (await getToken()) ?? undefined;
      return getMarketplaceLineage(id, { token });
    },
    [getToken],
  );

  const handlePublish = React.useCallback(
    async (body: PublishTemplateRequest) => {
      const token = (await getToken()) ?? undefined;
      await publishTemplate(body, { token });
      setPublishOpen(false);
      void load();
    },
    [getToken, load],
  );

  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
          <div className="flex items-center gap-3">
            <Button asChild variant="outline" size="sm">
              <Link href="/reels">Your reels</Link>
            </Button>
            <Button size="sm" onClick={() => setPublishOpen(true)}>
              <Upload className="size-4" aria-hidden /> Publish template
            </Button>
            <UserButton />
          </div>
        </div>
      </header>

      <section className="container py-8">
        <div className="mb-6 flex items-end justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
              <Store className="size-6 text-primary" aria-hidden />
              Template Marketplace
            </h1>
            <p className="text-sm text-muted-foreground">
              Browse community templates, clone them into your library, and rate
              the ones you love.
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load()}
            disabled={status === "loading"}
          >
            <RefreshCw
              className={status === "loading" ? "size-4 animate-spin" : "size-4"}
              aria-hidden
            />
            Refresh
          </Button>
        </div>

        <div className="mb-6">
          <MarketplaceFilters
            query={query}
            tag={tag}
            language={language}
            sort={sort}
            onQueryChange={setQuery}
            onTagChange={setTag}
            onLanguageChange={setLanguage}
            onSortChange={setSort}
          />
        </div>

        {status === "loading" && <MarketplaceSkeleton />}

        {status === "error" && (
          <ErrorPanel message={errorMessage} onRetry={() => void load()} />
        )}

        {status === "ready" && templates.length === 0 && (
          <EmptyState onPublish={() => setPublishOpen(true)} />
        )}

        {status === "ready" && templates.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {templates.map((template) => (
              <TemplateCard
                key={template.id}
                template={template}
                onClone={handleClone}
                onRate={handleRate}
                onLineage={handleLineage}
              />
            ))}
          </div>
        )}
      </section>

      <PublishDialog
        open={publishOpen}
        onClose={() => setPublishOpen(false)}
        onPublish={handlePublish}
      />
    </main>
  );
}

function MarketplaceSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <Card key={i}>
          <CardContent className="space-y-4 p-5">
            <div className="flex items-start justify-between gap-3">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-5 w-16" />
            </div>
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
            <div className="flex gap-1.5">
              <Skeleton className="h-5 w-16 rounded-full" />
              <Skeleton className="h-5 w-16 rounded-full" />
            </div>
            <Skeleton className="h-9 w-full rounded-md" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function ErrorPanel({
  message,
  onRetry,
}: Readonly<{ message: string; onRetry: () => void }>) {
  return (
    <Card className="border-destructive/40 bg-destructive/5">
      <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <AlertTriangle
            className="mt-0.5 size-5 shrink-0 text-destructive"
            aria-hidden
          />
          <div>
            <p className="font-medium">Couldn&apos;t load the marketplace</p>
            <p className="text-sm text-muted-foreground">{message}</p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="size-4" aria-hidden /> Try again
        </Button>
      </CardContent>
    </Card>
  );
}

function EmptyState({ onPublish }: Readonly<{ onPublish: () => void }>) {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center gap-4 py-16 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-primary/10">
          <Store className="size-6 text-primary" aria-hidden />
        </span>
        <div>
          <p className="font-medium">No templates found</p>
          <p className="text-sm text-muted-foreground">
            Try clearing your filters, or be the first to publish one.
          </p>
        </div>
        <Button onClick={onPublish}>
          <Upload className="size-4" aria-hidden /> Publish a template
        </Button>
      </CardContent>
    </Card>
  );
}
