"use client";

import * as React from "react";
import { LayoutGrid } from "lucide-react";
import type { LayoutOption } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { useLayouts } from "@/components/catalog/use-catalog";
import {
  CardGridSkeleton,
  EmptyState,
  ErrorPanel,
} from "@/components/catalog/states";
import { Pagination, usePaginated } from "@/components/catalog/Pagination";
import { SearchBar } from "@/components/catalog/SearchBar";

const PAGE_SIZE = 12;

function matches(layout: LayoutOption, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    layout.name.toLowerCase().includes(q) ||
    String(layout.id).toLowerCase().includes(q) ||
    layout.description.toLowerCase().includes(q)
  );
}

/** Searchable, paginated grid of composition-layout presets. */
export function LayoutsBrowser() {
  const { status, data, error, reload } = useLayouts();
  const [query, setQuery] = React.useState("");

  const layouts = data ?? [];
  const filtered = React.useMemo(
    () => layouts.filter((l) => matches(l, query)),
    [layouts, query],
  );
  const { page, pageCount, pageItems, setPage } = usePaginated(
    filtered,
    PAGE_SIZE,
  );

  if (status === "loading") return <CardGridSkeleton lines={2} />;
  if (status === "error") {
    return (
      <ErrorPanel
        title="Couldn't load composition layouts"
        message={error}
        onRetry={reload}
      />
    );
  }
  if (layouts.length === 0) {
    return (
      <EmptyState
        title="No layouts"
        message="The composition-layout catalog is empty right now."
        icon={<LayoutGrid className="size-6" aria-hidden />}
      />
    );
  }

  return (
    <div>
      <SearchBar
        value={query}
        onChange={setQuery}
        placeholder="Search layouts"
        resultLabel={`${filtered.length} of ${layouts.length}`}
        className="mb-6"
      />

      {filtered.length === 0 ? (
        <EmptyState
          title="No matches"
          message={`No layout matches "${query}".`}
          icon={<LayoutGrid className="size-6" aria-hidden />}
        />
      ) : (
        <>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {pageItems.map((layout) => (
              <li key={String(layout.id)}>
                <LayoutCard layout={layout} />
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

function LayoutCard({ layout }: Readonly<{ layout: LayoutOption }>) {
  return (
    <Card className="h-full">
      <CardContent className="flex h-full flex-col gap-3 p-5">
        <div className="flex items-start justify-between gap-3">
          <h3 className="font-semibold leading-tight">{layout.name}</h3>
          <Badge variant="outline">{String(layout.id)}</Badge>
        </div>
        <p className="flex-1 text-sm text-muted-foreground">
          {layout.description}
        </p>
        <div
          className="flex items-center justify-center gap-2 rounded-md bg-secondary/40 px-3 py-6"
          aria-hidden
        >
          <span className="flex h-16 w-9 items-center justify-center rounded border border-border bg-background">
            <LayoutGrid className="size-4 text-muted-foreground" />
          </span>
        </div>
        <p className="text-xs text-muted-foreground">
          Sent as <code className="rounded bg-secondary px-1 py-0.5">layout</code>
        </p>
      </CardContent>
    </Card>
  );
}
