"use client";

import * as React from "react";
import { useList } from "@refinedev/core";
import type { BaseRecord } from "@refinedev/core";
import { ChevronLeft, ChevronRight, Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

/** One rendered column of an admin table. */
export interface Column<TRow> {
  key: string;
  header: string;
  render: (row: TRow) => React.ReactNode;
  className?: string;
}

export interface ResourceTableProps<TRow extends BaseRecord> {
  /** refine resource name (must match a resource registered in AdminProviders). */
  resource: string;
  columns: readonly Column<TRow>[];
  /** Rows per page (also the backend `limit`, clamped 1..200 server-side). */
  pageSize?: number;
  /** Optional trailing actions cell (e.g. an impersonate button). */
  renderActions?: (row: TRow) => React.ReactNode;
  /** Stable row key; defaults to `row.id`. */
  rowKey?: (row: TRow) => string;
}

/**
 * A headless, refine-driven admin table: reads a cross-tenant resource via
 * `useList` (which calls the platform-admin data provider → FastAPI `/admin/*`)
 * and renders it with the app's own UI primitives. Offset pagination is inferred
 * (the endpoints return no total count), so "next" is enabled while a full page
 * comes back. Never renders another tenant's data — the server hard-gates every
 * page on `is_staff`.
 */
export function ResourceTable<TRow extends BaseRecord>({
  resource,
  columns,
  pageSize = 50,
  renderActions,
  rowKey,
}: ResourceTableProps<TRow>) {
  const [currentPage, setCurrentPage] = React.useState(1);

  const { query, result } = useList<TRow>({
    resource,
    pagination: { currentPage, pageSize, mode: "server" },
  });

  const rows = result?.data ?? [];
  const total = result?.total;
  const isLoading = query.isLoading;
  const isFetching = query.isFetching;
  const hasNext =
    typeof total === "number"
      ? currentPage * pageSize < total
      : rows.length === pageSize;

  const keyFor = React.useCallback(
    (row: TRow, index: number) =>
      rowKey ? rowKey(row) : String(row.id ?? index),
    [rowKey],
  );

  const colSpan = columns.length + (renderActions ? 1 : 0);

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-secondary/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              {columns.map((col) => (
                <th key={col.key} className="px-3 py-2 font-medium">
                  {col.header}
                </th>
              ))}
              {renderActions && (
                <th className="px-3 py-2 text-right font-medium">Actions</th>
              )}
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              [0, 1, 2, 3, 4].map((i) => (
                <tr key={i} className="border-b border-border last:border-b-0">
                  <td className="px-3 py-2" colSpan={colSpan}>
                    <Skeleton className="h-5 w-full" />
                  </td>
                </tr>
              ))
            ) : query.isError ? (
              <tr>
                <td
                  className="px-3 py-6 text-center text-sm text-destructive"
                  colSpan={colSpan}
                  role="alert"
                >
                  {query.error?.message ?? "Couldn't load this resource."}
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td
                  className="px-3 py-8 text-center text-sm text-muted-foreground"
                  colSpan={colSpan}
                >
                  Nothing to show on this page.
                </td>
              </tr>
            ) : (
              rows.map((row, index) => (
                <tr
                  key={keyFor(row, index)}
                  className="border-b border-border last:border-b-0"
                >
                  {columns.map((col) => (
                    <td key={col.key} className={col.className ?? "px-3 py-2"}>
                      {col.render(row)}
                    </td>
                  ))}
                  {renderActions && (
                    <td className="px-3 py-2 text-right">{renderActions(row)}</td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2 text-sm text-muted-foreground">
          Page {currentPage}
          {isFetching && !isLoading && (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          )}
        </span>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void query.refetch()}
            disabled={isFetching}
          >
            <RefreshCw
              className={isFetching ? "size-4 animate-spin" : "size-4"}
              aria-hidden
            />
            Refresh
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            disabled={currentPage === 1 || isFetching}
          >
            <ChevronLeft className="size-4" aria-hidden />
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setCurrentPage((p) => p + 1)}
            disabled={!hasNext || isFetching}
          >
            Next
            <ChevronRight className="size-4" aria-hidden />
          </Button>
        </div>
      </div>
    </div>
  );
}
