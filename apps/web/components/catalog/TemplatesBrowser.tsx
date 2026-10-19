"use client";

import * as React from "react";
import Link from "next/link";
import { Clapperboard, Clock, LayoutGrid, Sparkles, Type } from "lucide-react";
import type { Template } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useTemplates } from "@/components/catalog/use-catalog";
import {
  CardGridSkeleton,
  EmptyState,
  ErrorPanel,
} from "@/components/catalog/states";
import { Pagination, usePaginated } from "@/components/catalog/Pagination";
import { SearchBar } from "@/components/catalog/SearchBar";

const PAGE_SIZE = 9;

function matches(template: Template, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    template.name.toLowerCase().includes(q) ||
    template.id.toLowerCase().includes(q) ||
    template.description.toLowerCase().includes(q) ||
    template.video_subject.toLowerCase().includes(q)
  );
}

/** Format a duration in seconds as `Ns` or `Mm Ss`. */
function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

/** Searchable, paginated grid of curated reel templates with a "use" action. */
export function TemplatesBrowser() {
  const { status, data, error, reload } = useTemplates();
  const [query, setQuery] = React.useState("");

  const templates = data ?? [];
  const filtered = React.useMemo(
    () => templates.filter((t) => matches(t, query)),
    [templates, query],
  );
  const { page, pageCount, pageItems, setPage } = usePaginated(
    filtered,
    PAGE_SIZE,
  );

  if (status === "loading") return <CardGridSkeleton lines={3} />;
  if (status === "error") {
    return (
      <ErrorPanel
        title="Couldn't load templates"
        message={error}
        onRetry={reload}
      />
    );
  }
  if (templates.length === 0) {
    return (
      <EmptyState
        title="No templates"
        message="The template catalog is empty right now. Check back soon."
        icon={<Sparkles className="size-6" aria-hidden />}
      />
    );
  }

  return (
    <div>
      <SearchBar
        value={query}
        onChange={setQuery}
        placeholder="Search templates by name or subject"
        resultLabel={`${filtered.length} of ${templates.length}`}
        className="mb-6"
      />

      {filtered.length === 0 ? (
        <EmptyState
          title="No matches"
          message={`No template matches "${query}".`}
          icon={<Sparkles className="size-6" aria-hidden />}
        />
      ) : (
        <>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {pageItems.map((template) => (
              <li key={template.id}>
                <TemplateCard template={template} />
              </li>
            ))}
          </ul>
          <Pagination
            page={page}
            pageCount={pageCount}
            totalItems={filtered.length}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}

function TemplateCard({ template }: Readonly<{ template: Template }>) {
  const startHref = `/new?template=${encodeURIComponent(template.id)}`;
  return (
    <Card className="h-full">
      <CardContent className="flex h-full flex-col gap-3 p-5">
        <div className="flex items-start justify-between gap-3">
          <h3 className="font-semibold leading-tight">{template.name}</h3>
          <Badge variant="outline">{template.id}</Badge>
        </div>
        <p className="text-sm text-muted-foreground">{template.description}</p>
        <p className="line-clamp-2 rounded-md bg-secondary/40 px-3 py-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Subject:</span>{" "}
          {template.video_subject}
        </p>
        <div className="mt-auto flex flex-wrap items-center gap-2 pt-1 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <LayoutGrid className="size-3.5" aria-hidden />
            {String(template.layout)}
          </span>
          <span className="inline-flex items-center gap-1">
            <Type className="size-3.5" aria-hidden />
            {template.caption_style}
          </span>
          <span className="inline-flex items-center gap-1">
            <Clock className="size-3.5" aria-hidden />
            {formatDuration(template.target_duration_s)}
          </span>
          <Badge variant="secondary">{String(template.language)}</Badge>
        </div>
        <Button asChild size="sm" className="mt-2 w-full">
          <Link href={startHref}>
            <Clapperboard className="size-4" aria-hidden /> Use this template
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}
