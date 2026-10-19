"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface PaginationProps {
  page: number;
  pageCount: number;
  totalItems: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}

/**
 * Client-side pager for a locally-held catalog list. Shows the current window
 * ("N-M of T") and previous/next controls. Page numbers are 1-indexed.
 */
export function Pagination({
  page,
  pageCount,
  totalItems,
  pageSize,
  onPageChange,
}: Readonly<PaginationProps>) {
  if (pageCount <= 1) return null;

  const first = (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, totalItems);

  return (
    <nav
      className="mt-6 flex items-center justify-between gap-4"
      aria-label="Pagination"
    >
      <p className="text-sm text-muted-foreground">
        <span className="font-medium text-foreground">
          {first}&ndash;{last}
        </span>{" "}
        of {totalItems}
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          aria-label="Previous page"
        >
          <ChevronLeft className="size-4" aria-hidden /> Prev
        </Button>
        <span className="text-sm tabular-nums text-muted-foreground">
          {page} / {pageCount}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= pageCount}
          aria-label="Next page"
        >
          Next <ChevronRight className="size-4" aria-hidden />
        </Button>
      </div>
    </nav>
  );
}

export interface UsePaginatedResult<T> {
  page: number;
  pageCount: number;
  pageItems: readonly T[];
  setPage: (page: number) => void;
}

/**
 * Derives a stable paginated window over `items`. Resets to page 1 whenever the
 * item count changes (e.g. after a search filter narrows the list).
 */
export function usePaginated<T>(
  items: readonly T[],
  pageSize: number,
): UsePaginatedResult<T> {
  const [page, setPage] = React.useState(1);
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));

  React.useEffect(() => {
    setPage(1);
  }, [items.length]);

  const safePage = Math.min(page, pageCount);
  const start = (safePage - 1) * pageSize;
  const pageItems = items.slice(start, start + pageSize);

  return { page: safePage, pageCount, pageItems, setPage };
}
