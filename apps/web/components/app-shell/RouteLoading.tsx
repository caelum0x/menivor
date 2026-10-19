import { Skeleton } from "@/components/ui/skeleton";

interface RouteLoadingProps {
  /** What is loading, read to screen readers (e.g. "your reels"). */
  readonly label: string;
  /** Layout of the placeholder body: a card grid, a list, or a single panel. */
  readonly variant?: "grid" | "list" | "panel";
}

const GRID_ITEMS = [0, 1, 2, 3, 4, 5] as const;
const LIST_ROWS = [0, 1, 2, 3, 4] as const;

/**
 * Shared route-segment loading state. Reserves the app header, a page title
 * and a body shaped like the page, so navigation shows structure immediately
 * instead of a blank screen while the segment's data streams in.
 */
export function RouteLoading({ label, variant = "grid" }: RouteLoadingProps) {
  return (
    <div aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading {label}…</span>
      <div className="border-b border-border" aria-hidden>
        <div className="container flex h-16 items-center justify-between gap-3">
          <Skeleton className="h-5 w-28" />
          <div className="flex items-center gap-2">
            <Skeleton className="h-9 w-24" />
            <Skeleton className="h-9 w-9 rounded-full" />
          </div>
        </div>
      </div>
      <main className="container space-y-6 py-8" aria-hidden>
        <div className="space-y-2">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-4 w-80 max-w-full" />
        </div>
        {variant === "grid" ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {GRID_ITEMS.map((i) => (
              <Skeleton key={i} className="h-40 w-full" />
            ))}
          </div>
        ) : null}
        {variant === "list" ? (
          <div className="space-y-3">
            {LIST_ROWS.map((i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : null}
        {variant === "panel" ? <Skeleton className="h-[28rem] w-full" /> : null}
      </main>
    </div>
  );
}
