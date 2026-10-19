import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface ReelsPaginationProps {
  page: number;
  pageCount: number;
  from: number;
  to: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
}

/**
 * Footer pager for the reels table. Shows the visible range ("1–10 of 42") and
 * previous/next controls, disabled at the ends of the list.
 */
export function ReelsPagination({
  page,
  pageCount,
  from,
  to,
  total,
  onPrev,
  onNext,
}: Readonly<ReelsPaginationProps>) {
  return (
    <div className="flex items-center justify-between gap-4 border-t border-border px-4 py-3 text-sm text-muted-foreground">
      <p>
        {total === 0 ? (
          "No reels"
        ) : (
          <>
            <span className="font-medium text-foreground">
              {from}–{to}
            </span>{" "}
            of {total}
          </>
        )}
      </p>
      <div className="flex items-center gap-2">
        <span className="hidden sm:inline">
          Page {page} of {pageCount}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={onPrev}
          disabled={page <= 1}
          aria-label="Previous page"
        >
          <ChevronLeft className="size-4" aria-hidden />
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onNext}
          disabled={page >= pageCount}
          aria-label="Next page"
        >
          <ChevronRight className="size-4" aria-hidden />
        </Button>
      </div>
    </div>
  );
}
